"""The BETA polish calculator, executed out of the real frontend/js/polish-estimate.js.

WHAT CHANGED, AND WHY EVERY ASSERTION HERE RUNS THE PAGE.

2026-08-17: the beta dropped from seven HyperFormula-driven sub-steps to three self-pricing ones.
The workbook is gone from this screen. Will asked for a takeoff whose rows are ASSEMBLIES out of the
Items & Assemblies library, labor lines an estimator can add, and the markup chain shown as its own
reviewable block — none of which the Polish worksheet has a cell for. So the page prices itself, and
the connection to Kyle's file is kept a different way: polish-bid-core.js transcribes his markup
column and tests/test_polish_markup_parity.py fails if the two ever disagree.

That moved what these tests have to protect. The old file asserted engine loading, named
expressions, cell_values replay and seven steps; all of it is deleted, because none of it exists.
What can go wrong now is arithmetic and addressing:

  * **A second opinion on price.** The row must show the library's own figure for that assembly at
    that measurement, or the same assembly costs one thing on the Item Library page and another
    here. Checked by pricing the fixture with the REAL library-core.js and comparing the number the
    page put in the cell — never against a literal, because a literal only pins today's fixture.
  * **A transposed or off-by-one write.** library.js addressed its computed cells by column index
    and shipped Quantity and Cost written into each other's columns. The test compared
    `var QTY_TD = 4, COST_TD = 5` against the rendered columns, the two agreed, and the bug reached
    staging. So this file builds the cell graph FROM the render functions' own output and runs the
    real repaint against it, with more than one row on screen.
  * **An unbound identifier in a handler.** Invisible to a source assertion; STAGE_CREATED took the
    board down on prod on 2026-08-12 with every source test green. Every handler here is fired.
  * **A save that lies to the rest of the app.** `_bid_total` in backend/drafts.py reads
    computed_bid.full_bid.total_base_bid for the projects card, and proposal-review falls back to
    it for the lump sum. Checked by reading the payload handed to TW.setState.

The harness (tests/js/polish-estimate-harness.js) executes the page's ENTIRE IIFE body — nothing is
lifted out function by function, because a function it forgot to lift would be a function no test
ever ran — with only `init();` taken off the bottom so boot can be driven. fetch, TW, TWAuth, the
sandbox module, the DOM and the clock are stubbed. polish-bid-core.js and library-core.js are the
real modules, so the arithmetic under test is the shipped arithmetic.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "polish-estimate-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def html():
    return (FRONTEND / "polish-estimate.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def js():
    return (FRONTEND / "js" / "polish-estimate.js").read_text(encoding="utf-8")


def dollars(text):
    """A rendered money cell back to a number: "-$648" -> -648.0, "$1,884" -> 1884.0."""
    s = str(text).strip()
    neg = s.startswith("-")
    s = s.lstrip("-").lstrip("$").replace(",", "")
    return -float(s) if neg else float(s)


def as_shown(value):
    """What moneyAuto() puts on screen, as a number: whole dollars unless there are real cents."""
    v = float(value)
    return float(round(v)) if abs(v - round(v)) < 0.005 else round(v, 2)


def money_is(rendered, expected, what=""):
    assert dollars(rendered) == pytest.approx(as_shown(expected), abs=0.005), (
        "%s: the page shows %r, the engine says %r" % (what, rendered, expected))


# ── A. the takeoff row shows the LIBRARY's price, not one of its own ──────────
@needs_node
def test_a_takeoff_row_shows_the_librarys_own_price(ran):
    """Each row's cost cell is compared with library-core's priceAssembly() for that assembly at
    that measurement — the same function the Item Library page shows its own totals with. Not a
    literal: a literal pins this fixture, not the agreement between the two screens.

    The moment a price is computed here instead, the same assembly costs one thing on the library
    page and another on the bid, and nothing on either screen says so.

    Mutation: in rowPrice(), `L.priceAssembly(asm, ITEMS, B.num(r.measurement) * 1.05)` — a waste
    factor applied a second time on top of the one the library line already carries."""
    for row in ran["takeoff"]["rows"]:
        money_is(row["renderedCost"], row["expectedTotal"], "takeoff row %d" % row["i"])
        assert row["expectedTotal"] > 0, "the fixture row priced at nothing; it proves nothing"
    # And the per-unit hint under it, which is what an estimator sanity-checks against a past job.
    for row in ran["takeoff"]["rows"]:
        got = float(row["renderedPerUnit"].split(" ")[0].lstrip("$"))
        assert got == pytest.approx(round(row["expectedPerUnit"], 2), abs=0.005)


@needs_node
def test_the_cents_show_only_when_there_are_cents(ran):
    """moneyAuto's two branches. Kyle's sheet shows whole dollars and a column of "$3,864.00" reads
    heavy — but hiding cents under a total that sums the exact figures is how "11 × $85.38" ended up
    printed under $939.21 on the library page. Round figures stay round; a fraction says so.

    Row 2 of the fixture is a flat $100 per 1,000 SF over 5,000 SF, so it lands on $500 exactly;
    rows 0 and 1 do not.

    Mutation: `return B.money(v);` — the cents branch dropped, and every fractional line rounds on
    screen while the total below it does not."""
    rows = ran["takeoff"]["rows"]
    assert "." not in rows[2]["renderedCost"], (
        "a whole-dollar line is showing cents: %r" % rows[2]["renderedCost"])
    for i in (0, 1):
        assert re.search(r"\.\d\d$", rows[i]["renderedCost"]), (
            "a fractional line is rounded on screen: %r" % rows[i]["renderedCost"])
    # The fractional one is a not-rounded-up line — buy exactly what is needed, at unit price.
    money_is(rows[1]["renderedCost"], rows[1]["expectedTotal"], "the fractional row")


@needs_node
def test_the_material_total_and_the_measured_area_are_the_rows_added_up(ran):
    """The caption under the takeoff sums the rows, and the AREA deliberately excludes the LF ones.
    C82 of the Polish tab divides the bid by an area; adding 200 LF of cove to 17,500 SF of floor
    gives a price-per-SF that is quietly wrong on every job with a cove.

    Mutation: `B.takeoffSf` swapped for a plain sum of measurements — 17,700 SF instead of 17,500,
    and the per-SF figure the customer is quoted moves."""
    t = ran["takeoff"]
    money_is(t["matTotal"], t["expectedMaterial"], "material total")
    assert t["areaTotal"] == "17,500 SF", (
        "the measured area is not the SF rows only: %r" % t["areaTotal"])
    assert t["expectedArea"] == 17500
    assert t["rows"][1]["renderedMeasure"] == "200 LF", "the LF row lost its unit on screen"
    money_is(t["bidTotal"], t["expectedChain"]["total"], "the bid bar")


@needs_node
def test_a_row_whose_material_left_the_library_says_so(ran):
    """priceAssembly reports broken lines rather than pricing them at zero, and the row has to pass
    that on — an assembly that silently prices at nothing understates a bid with no warning.

    Mutation: drop the `p.broken_lines` block from takeoffPanel()."""
    warn = ran["takeoff"]["brokenWarning"]
    assert warn and "cannot price yet" in warn, (
        "an assembly whose material was deleted renders no warning: %r" % warn)
    assert "library" in warn, "the warning does not say where to go and fix it"
    # And the cost box agrees with the warning instead of contradicting it.
    assert ran["takeoff"]["brokenCost"] == "—", (
        "a row that cannot price shows a figure (%r) above a warning saying it cannot price"
        % ran["takeoff"]["brokenCost"])
    assert "empty" in ran["takeoff"]["brokenClass"]


@needs_node
def test_a_picked_but_unmeasured_row_reads_as_unmeasured_not_as_free(ran):
    """"$0" and "—" are different claims. priceAssembly returns a legitimate {total: 0} for an
    assembly with no measurement, so printing it says the row costs NOTHING when the truth is that
    nobody has said how much of it there is — and that is the state every row sits in for the whole
    time between picking an assembly and typing a number.

    Both engines already refuse this for their own per-unit figures, in those words:
    library-core.js's `per_unit` is null because 0 "would read as 'free' rather than 'unknown'",
    and polish-bid-core.js says the same of `per_sf`. The cost box has to agree with them.

    Mutation: `return { text: moneyAuto(p.total), empty: false }` unconditionally in rowCost()."""
    u = ran["takeoff"]["unmeasured"]
    assert u["text"] == "—", "a picked-but-unmeasured row reads as free: %r" % u["text"]
    assert "empty" in u["className"], (
        "the cost box is styled as a real figure while showing a placeholder")
    # Typing a measurement gives a real figure, and clearing it goes back — through the repaint
    # path, not the panel builder, which is the path that would keep a stale "$0" on screen.
    assert ran["takeoff"]["afterTyping"] not in ("—", "$0"), (
        "a measured row still shows no price: %r" % ran["takeoff"]["afterTyping"])
    assert ran["takeoff"]["afterClearing"]["text"] == "—", (
        "clearing the measurement left the old price on screen: %r"
        % ran["takeoff"]["afterClearing"]["text"])
    assert "empty" in ran["takeoff"]["afterClearing"]["className"]


# ── B. the assembly picker ───────────────────────────────────────────────────
@needs_node
def test_the_assembly_picker_resolves_exact_then_unique_case_insensitive(ran):
    """The documented rule, and only it: exact name first, then a UNIQUE case-insensitive match.
    Never a fuzzy guess — the same rule as the material picker on the library page.

    Mutation: add a `indexOf(lc) === 0` prefix fallback. "Polish 800" would then resolve to
    "Polish 800 Grit" and an estimator who stopped typing gets a system they did not choose."""
    p = ran["picker"]
    assert p["exact"] == "a1"
    assert p["uniqueCaseInsensitive"] == "a2", "a unique case-insensitive name did not resolve"
    assert p["trimmed"] == "a2", "surrounding whitespace defeats the picker"
    assert p["partialRefused"] is None, "a partial name resolved to a whole assembly"
    assert p["unknownRefused"] is None and p["blank"] is None


@needs_node
def test_two_assemblies_differing_only_by_case_resolve_to_nothing(ran):
    """"Grind & Seal" and "GRIND & SEAL" both exist in the fixture. Typing either one EXACTLY gets
    that one; typing it in any other case gets NOTHING. Two assemblies whose names differ only by
    case is a library problem to fix in the library, not something to resolve by picking one of them
    here — one of them is somebody's older version and the difference is thousands of dollars.

    Mutation: `return hits[0];` instead of `hits.length === 1 ? hits[0] : null`. Whichever assembly
    happens to sort first in the API response wins, and the bid changes when the library is
    re-ordered."""
    p = ran["picker"]
    assert p["exactBeatsTheTwin"] == "a3", "an exact name lost to its case-insensitive twin"
    assert p["exactBeatsTheTwinUpper"] == "a4"
    assert p["ambiguousCase"] is None, "an ambiguous case-only match was resolved anyway"
    assert p["ambiguousCaseMixed"] is None


@needs_node
def test_unknown_text_clears_the_id_and_keeps_what_was_typed(ran):
    """setAssembly must leave assembly_id empty so blockers() can say "Pick an assembly for takeoff
    row 1" — and must KEEP the typed name, or the estimator's own words vanish out of the box while
    they are still looking at it.

    Mutation: `if (asm) row.assembly_name = text;` — the typed text is discarded on a miss, the box
    reverts, and nothing explains why."""
    u = ran["picker"]["unknownKeepsTheText"]
    assert u["id"] == "", "unknown text still left an assembly id on the row"
    assert u["name"] == "Terrazzo Polish", "the typed name was thrown away"
    assert "Pick an assembly for takeoff row 1" in u["blockers"], (
        "the review step will not complain about the unfinished row: %r" % u["blockers"])


@needs_node
def test_the_unit_follows_the_assembly_only_when_the_pick_changes(ran):
    """An LF assembly stamps LF on the row, on the model AND on the <select> the page rendered.
    But once the estimator has overridden it by hand, re-typing the same assembly must NOT snap it
    back: assembly_id has not changed, so there is no new pick to adopt.

    Mutation: move the unit adoption outside the `row.assembly_id !== before` guard. Every keystroke
    in the assembly box then re-stamps the unit, and a hand-set SF row flips to LF while it is being
    edited — which also silently drops it out of the measured area."""
    u = ran["unit"]
    assert u["before"] == "SF"
    assert u["afterPick"]["unit"] == "LF", "the row did not adopt the assembly's unit"
    assert u["afterPick"]["select"] == "LF", (
        "the model changed but the dropdown on screen still shows the old unit")
    assert u["afterHand"] == "SF", "the change handler did not record a hand-set unit"
    assert u["afterRetype"] == "SF", (
        "re-typing the same assembly re-stamped the unit over the estimator's own choice")
    assert u["afterDifferentPick"] == "SF", "a genuinely new pick did not adopt its unit"


# ── C. typing repaints, it does not rebuild ──────────────────────────────────
@needs_node
def test_typing_a_measurement_repaints_without_rebuilding_the_panel(ran):
    """`changed(false)` refreshes the computed figures in place. Rebuilding the panel mid-keystroke
    takes the caret out of the field being typed in, which makes the box unusable for anything
    longer than one digit.

    Mutation: `changed(true)` in the input handler. Everything shows the right number and the field
    loses focus after every character."""
    t = ran["typing"]
    assert t["noRebuild"], "the panel was re-rendered on an `input` event (%d rebuilds)" % t[
        "rebuilds"]
    assert t["fieldUntouched"], "the field under the caret was written to by the repaint"
    money_is(t["costNow"], t["expectedCost"], "the row's cost after typing")
    assert t["costNow"] != t["costWas"], "the cost cell never moved"
    assert t["measureNow"] == "20,000 SF", (
        "the row header still shows the old measurement: %r" % t["measureNow"])
    money_is(t["matTotalNow"], t["expectedMaterialSum"], "material total after typing")
    assert t["areaTotalNow"] == "25,000 SF"


@needs_node
def test_each_rows_cost_lands_in_its_own_rows_cell(ran):
    """THE TRANSPOSITION / OFF-BY-ONE CLASS, stated directly. Three rows on screen; row 0 is edited;
    rows 1 and 2 must still hold their own prices. This is the exact failure the data attributes
    exist to make impossible — library.js addressed its cells by column index, wrote Quantity and
    Cost into each other's columns, and shipped, because its test compared the index constants with
    the rendered columns and they agreed.

    Mutation: in repaintNumbers, `rowPrice(M.takeoff[i + 1])`, or `rowPrice(M.takeoff[0])`. Every
    figure on screen is a real price of a real row — just not of the row it is sitting in."""
    t = ran["typing"]
    assert t["othersUnmoved"] == [True, True], (
        "editing row 0 changed another row's cost cell: %r / %r" % (t["row1Cost"], t["row2Cost"]))
    money_is(t["row1Cost"], t["expectedRow1"], "row 1 after editing row 0")
    money_is(t["row2Cost"], t["expectedRow2"], "row 2 after editing row 0")
    assert ran["takeoff"]["costCells"] == 3, (
        "three takeoff rows did not render three cost cells: %r" % ran["takeoff"]["costCells"])


@needs_node
def test_typing_a_labor_figure_repaints_that_rows_cost_and_the_total(ran):
    """The same contract on the labor table, where the cells sit in a <tr> and a positional updater
    would be even easier to write.

    Mutation: `[data-lcost-for]` repainted from `M.labor[0]` regardless of the attribute — every
    line then shows the first line's cost."""
    lab = ran["typing"]["labor"]
    assert lab["noRebuild"], "the labor panel was rebuilt on an `input` event"
    money_is(lab["costNow"], lab["expectedCost"], "the edited labor line")
    assert lab["costNow"] != lab["costWas"]
    money_is(lab["totalNow"], lab["expectedTotal"], "labor total")
    assert lab["otherUnmoved"], (
        "editing labor line 0 moved line 1's cost cell to %r" % lab["row1Cost"])


# ── D. labor maths, and the add/remove lines ─────────────────────────────────
@needs_node
def test_a_day_is_eight_hours(ran):
    """Kyle's own screenshot: 3 guys × 5 days × $32.20 = $3,864. D37 is
    `=(A37*B37*C37)*IF($E$35="8 hour days",8,10)` and E35 says "8 hour days" — that $3,864 is the
    only thing pinning the 8 rather than the 10, and it is read off the cell the page rendered
    rather than off the core module, so the screen is what is being pinned.

    Mutation: HOURS_PER_DAY = 10. Every polish bid rises about 25% on the labor side, and the
    figures still look entirely plausible."""
    lab = ran["labor"]
    assert lab["hoursPerDay"] == 8
    assert lab["anchorCell"] == "$3,864", (
        "3 guys x 5 days x $32.20 does not come to $3,864 on screen: %r" % lab["anchorCell"])
    money_is(lab["anchorCell"], lab["anchorExpected"], "the anchor row")
    # Half a day is half the money, so the hours are a multiplier and not a per-day flat rate.
    money_is(lab["halfDayCell"], lab["halfDayExpected"], "the half-day row")
    assert lab["halfDayCell"] == "$386.40"
    money_is(lab["totalCell"], lab["totalExpected"], "labor total")
    assert lab["headings"] == ["Task", "Guys", "Days", "Rate / day", "Cost", ""], (
        "the labor columns changed: %r" % lab["headings"])


@needs_node
def test_adding_a_labor_line_prices_from_its_own_values(ran):
    """Will asked for labor lines an estimator can add — the worksheet's eight rows were the reason
    the old page could not. The new row has to be editable and has to price from what was typed
    INTO IT, not from a sibling.

    Mutation: `newLaborRow()` returning a fixed id. Two added rows then share an id, and the next
    thing that keys off it (a save, a delete) touches the wrong one."""
    lab = ran["labor"]
    assert lab["afterAdd"]["count"] == 3, "the add button did not append a line"
    assert lab["newRowLabel"] == "Densify", "the new row's own text box does not reach the model"
    money_is(lab["newRowCost"], lab["newRowExpected"], "the added line")
    assert lab["newRowCost"] == "$1,920"
    assert lab["row0StillAnchored"] == "$3,864", (
        "adding a line moved an existing line's cost to %r" % lab["row0StillAnchored"])
    money_is(lab["totalAfterAdd"], lab["totalAfterAddExpected"], "labor total after the add")


@needs_node
def test_deleting_a_labor_line_removes_the_one_that_was_asked_for(ran):
    """Index 1 of [Polishing, Mock-up, Densify] is the mock-up. Deleting the wrong line is the
    quietest possible data loss: the table still looks full.

    Mutation: `M.labor.splice(i, 1)` where i comes from `data-del-lab` on the row above, or a
    `splice(i)` with no count — which truncates everything from there down."""
    lab = ran["labor"]
    assert lab["afterDelete"] == ["Polishing", "Densify"], (
        "the delete took the wrong line: %r" % lab["afterDelete"])
    assert lab["afterDeleteCells"] == 2, "the table still renders a cell for the deleted line"
    # The survivors keep their own money after the row between them went.
    assert lab["afterDeleteCosts"] == ["$3,864", "$1,920"], (
        "the rows below the deleted one did not keep their own costs: %r" % lab["afterDeleteCosts"])


@needs_node
def test_the_last_row_cannot_be_deleted_away_to_nothing(ran):
    """At one line the ✕ is not offered — and the guard behind it holds anyway when the button the
    page rendered a moment ago is pressed again. An empty table has no box to type in and no way
    back to one.

    Mutation: drop `if (!M.labor.length) M.labor.push(newLaborRow());`. The labor step renders an
    empty table and the estimator's only recovery is to reload."""
    lab = ran["labor"]
    assert lab["atOneRow"]["count"] == 1
    assert lab["atOneRow"]["deleteOffered"] == 0, (
        "a ✕ is still offered on the only remaining labor line")
    assert lab["afterDeletingTheLast"]["count"] == 1, (
        "the labor table was emptied: %r" % lab["afterDeletingTheLast"])
    assert lab["afterDeletingTheLast"]["cells"] == 1, "no labor row is rendered any more"
    assert lab["afterDeletingTheLast"]["labels"] == [""], (
        "the replacement row is not a fresh blank one: %r" % lab["afterDeletingTheLast"]["labels"])
    # Same guard on the takeoff side, where the row is what the whole bid is measured on.
    t = lab["takeoffNeverEmpty"]
    assert t["count"] == 1 and t["cells"] == 1, "the takeoff was deleted away to nothing: %r" % t
    assert t["row"]["assembly_id"] == "" and t["row"]["measurement"] == "", (
        "the replacement takeoff row carries the deleted row's values: %r" % t["row"])
    # And an added takeoff row opens empty, priced at nothing, saying where assemblies come from.
    a = lab["addedTakeoffRow"]
    assert a["count"] == 4 and a["cost"] == "—", (
        "a brand-new takeoff row does not read as unpriced: %r" % a["cost"])
    assert "Items & Assemblies" in a["hint"]


@needs_node
def test_money_columns_wear_the_dollar_sign(ran):
    """A rate is money and says so — with the "$" OUTSIDE the input, because a sign inside the box
    gets parsed as part of the number the estimator typed.

    Mutation: put the $ inside the value attribute. B.num() strips "$" so the arithmetic survives,
    which is exactly why this has to be checked on the markup rather than on the total."""
    lab = ran["labor"]
    assert lab["rateWearsADollar"], "the rate column lost its dollar sign, or took it inside the box"
    assert lab["costCellsWearADollar"], "a labor cost cell renders a bare number"


# ── E. review: the markup block IS the chain ──────────────────────────────────
@needs_node
def test_the_markup_block_is_the_chain_line_for_line(ran):
    """Every money cell in the review block is compared with polish-bid-core's markupChain() for the
    same model — the module that is pinned, formula string by formula string, to the Polish tab of
    Kyle's estimate_sheet_5.7.xlsx by tests/test_polish_markup_parity.py. So the screen is pinned to
    his workbook through that chain rather than by a number typed into this file.

    The fixture has prevailing wage, hard bid, sales tax and the remodel tax all ON, so no line of
    the chain is dark.

    Mutation: in bid(), pass `material: roundUp(materialTotal())`. D31 already rounds up, and
    rounding twice drifts the sub-total, which then drifts GP, super/PTO, soft costs and both
    taxes — a plausible bid, tens of dollars out, on every job."""
    r = ran["review"]
    exp = r["expected"]
    for key, cell in r["rendered"]["money"].items():
        assert key in exp, "the review shows a %r line the chain does not compute" % key
        money_is(cell, exp[key], "review line %r" % key)
    # The lines Kyle's sheet has, in the order he reads them down.
    for key in ("material", "shipping", "material_total", "labor", "escalation", "burden",
                "labor_total", "sub_total", "gp", "hard_bid", "super_pto", "soft_costs",
                "sales_tax", "remodel_tax", "taxes", "fees", "bond", "fees_and_bond", "total"):
        assert key in r["rendered"]["money"], "the review block has lost its %r line" % key
    assert r["rendered"]["persf"] == r["expectedPerSf"], (
        "the price per SF beside the lump sum is %r, not %r"
        % (r["rendered"]["persf"], r["expectedPerSf"]))
    # The hard-bid give-back is NEGATIVE. ROUNDUP away from zero makes it bigger, not smaller.
    assert dollars(r["rendered"]["money"]["hard_bid"]) < 0, (
        "the hard-bid discount is not a give-back: %r" % r["rendered"]["money"]["hard_bid"])


@needs_node
def test_the_percentage_column_is_the_chains_own_rates(ran):
    """Four of the rates move with the job — the GP band with the sub-total, the hard-bid discount
    with the sub-total and the Local flag, and the two taxes with their toggles. They are rendered
    from the chain's own output, not from RATES.

    Mutation: render `B.pct(B.RATES.SALES_TAX)` for the sales-tax row. It reads 9.475% on a job that
    is not taxable, beside a $0 amount."""
    r = ran["review"]
    assert r["rendered"]["pcts"] == r["expectedPct"], (
        "the percentage column disagrees with the chain: %r vs %r"
        % (r["rendered"]["pcts"], r["expectedPct"]))
    # 9.475%, not 9.48%: 9.5% is a different bid on a 40,000 SF floor.
    assert r["rendered"]["pcts"]["sales_tax_pct"] == "9.475%"


@needs_node
def test_contingency_feeds_super_pto_soft_costs_and_the_remodel_tax(ran):
    """Contingency is the one percentage-column line an estimator may set, because D71 is open in
    the sheet too. D69, D70 and D75 all take D71 into their base, so typing into it has to move
    three lines and the lump sum — in place, without rebuilding the panel under the caret.

    Mutation: drop `contingency` from the super/PTO base in markupChain — the total still rises by
    the contingency itself, so the number looks like it worked, and it is short by 2.7% + 16% of it
    on every bid."""
    c = ran["review"]["contingency"]
    assert c["noRebuild"], "typing a contingency rebuilt the review panel"
    assert c["model"] == "5000", "the typed contingency never reached the model"
    for key in ("super_pto", "soft_costs", "remodel_tax", "total"):
        assert c["after"]["money"][key] != c["before"][key], (
            "%r did not move when the contingency was set: still %r" % (key, c["before"][key]))
        money_is(c["after"]["money"][key], c["expected"][key], "%r with a contingency" % key)
    # And every other line of the chain is refreshed against the same recomputation.
    for key, cell in c["after"]["money"].items():
        money_is(cell, c["expected"][key], "%r with a contingency" % key)


@needs_node
def test_a_sub_total_that_crosses_a_gp_band_moves_the_percentage_in_place(ran):
    """B67 is banded: 52% under $6,500, then 45%, 35%, 32%, 30%. So the percentage column is as
    computed as the money column, and repaintNumbers has to refresh it. Driven through the page's
    own setAssembly() and changed(false) — the two calls the input handler makes, in that order,
    because the takeoff's measurement box is not on screen on the review step.

    Mutation: render the GP rate as plain text instead of a `data-mkpct` span. It is right when the
    panel is built and then stale for the rest of the session — 35% printed beside a GP amount
    computed at 45%."""
    g = ran["review"]["gpBand"]
    assert dollars(g["subAfter"]) < dollars(g["subBefore"]), "the fixture did not move the sub-total"
    assert g["pctBefore"] == g["expectedBefore"] == "35%"
    assert g["pctAfter"] == g["expectedAfter"] == "45%", (
        "the GP band was printed once and never refreshed: still %r" % g["pctAfter"])
    assert g["noRebuild"], "the panel was rebuilt, so this proves nothing about the repaint"
    money_is(g["gpAfter"], g["expectedGpAfter"], "GP at the new band")


@needs_node
def test_the_two_taxes_switched_off_are_zeroed_and_marked_off(ran):
    """B74 is `=IF($B$6="no",0,0.09475)` and B75 `=IF(D6="yes",0.1,0)`, and both flags live on the
    beta intake form now. A row that is off must read as off — zero, greyed, and pointing at the
    step that can turn it on — rather than quietly missing.

    Mutation: gate the rows on `b.sales_tax` instead of `b.sales_tax_pct`. A taxable job whose
    materials happen to price at nothing is then labelled "off · edit in Intake", which sends the
    estimator to flip a switch that is already on."""
    o = ran["review"]["off"]
    for key in ("sales_tax", "remodel_tax"):
        assert dollars(o["rendered"]["money"][key]) == 0, (
            "%r still charges something with its condition off: %r"
            % (key, o["rendered"]["money"][key]))
        assert o["rowClasses"][key] == "off", (
            "the %r row is not marked off: class=%r" % (key, o["rowClasses"][key]))
    assert o["rendered"]["pcts"]["sales_tax_pct"] == "0%"
    assert o["rendered"]["pcts"]["remodel_pct"] == "0%"
    assert o["salesTaxRowSaysWhere"] and o["remodelRowSaysWhere"], (
        "a switched-off tax row does not say where to turn it back on")
    # Hard bid off says WHY there is no discount, rather than showing a bare zero.
    assert o["rowClasses"]["hard_bid"] == "off" and o["hardBidReason"]
    # …and the whole block still agrees with the chain for that model.
    for key, cell in o["rendered"]["money"].items():
        money_is(cell, o["expected"][key], "review line %r with the taxes off" % key)
    # With the two taxes off, and only then, the escalation line is dark too (prevailing wage off).
    assert dollars(o["rendered"]["money"]["escalation"]) == 0


# ── F. the save contract ─────────────────────────────────────────────────────
@needs_node
def test_the_save_carries_what_the_rest_of_the_app_reads(ran):
    """`_bid_total` in backend/drafts.py reads computed_bid.full_bid.total_base_bid for the projects
    card and for every revision row; proposal-review falls back to it for the lump sum and itemises
    the two tax lines; /api/generate's files-mode rebuild gates on polish_sf. A save that omits one
    of them shows a priced beta project as having no total at all.

    Mutation: `total_base_bid: b.sub_total`. The card shows a number, it is simply the cost rather
    than the bid — about 35% light."""
    s = ran["save"]
    assert s["sentOnce"], "the edit produced %r saves" % s["sentOnce"]
    assert s["version"] == 2, "the saved model is not v2: %r" % s["version"]
    assert s["polishSf"] == s["expected"]["sf"] == 25000, (
        "polish_sf is not the measured area: %r" % s["polishSf"])
    fb = s["computed"]["full_bid"]
    assert fb["total_base_bid"] == s["expected"]["total"], (
        "the projects card would read %r, the chain says %r"
        % (fb["total_base_bid"], s["expected"]["total"]))
    assert fb["sales_tax"] == s["expected"]["sales_tax"]
    assert fb["remodel_tax"] == s["expected"]["remodel_tax"]
    assert s["computed"]["lump_sum"] == s["expected"]["total"]
    assert s["computed"]["price_per_sf"] == pytest.approx(s["expected"]["per_sf"])
    # The snapshot on the model itself, which is what a later read uses without re-pricing.
    assert s["modelTotals"] == s["expected"]["total"]


@needs_node
def test_the_save_writes_no_worksheet_cells(ran):
    """This page stopped writing state.cell_values when the workbook left it: there is no cell to
    write an assembly into. Writing a partial map would be worse than writing none — done.js posts
    the whole thing to /api/generate, and a half-filled Polish tab reads as a real estimate.

    Mutation: bring back a `cell_values` key. The downloaded .xlsx then shows figures that no longer
    match the screen, and there is nothing on either to say which is which.

    THE RESIDUAL HAZARD, stated rather than asserted away. The payload is
    `Object.assign({}, TW.getState(), {…})`, so a map a draft ALREADY carries — from the old
    seven-step beta, which did write Polish!* cells — rides through untouched. Generating that
    project would fill the worksheet from the old beta's figures while this screen shows the new
    ones. What is checked here is only what this page is responsible for: it contributes nothing to
    that map. Clearing a stale one would be an improvement and would still pass."""
    assert ran["save"]["hasCellValues"] is False, (
        "the save carries a cell_values map: %r" % ran["save"]["keys"])
    carried = ran["save"]["legacyCellValues"] or {}
    assert set(carried) <= {"Polish!D82"}, (
        "the page added a worksheet cell of its own to a draft that already had a map: %r" % carried)


@needs_node
def test_computed_bid_is_replaced_not_merged(ran):
    """On a sandbox copy the SOURCE project's computed_bid arrives with the blob. Merging would
    leave a real customer's figures sitting underneath a beta price — the projects card keeps showing
    the old total, or worse, a mix of both.

    Checked as an exact KEY SET at both levels, not just as "the stale total is gone". A merge that
    happens to overwrite every key the beta writes looks harmless on a fixture whose stale blob holds
    only those keys; the seed here carries an epoxy job's phase totals and the old tax-handling
    phrase precisely because those are what a merge leaves behind.

    Mutation: `computed_bid: Object.assign({}, TW.getState().computed_bid || {}, {…})` — the shape
    every other save on this page uses, and the wrong one here. Same again one level down, on
    `full_bid`."""
    s = ran["save"]
    assert s["staleTotalGone"], (
        "the source project's total is still in the payload: %r" % s["computed"])
    assert s["staleExtras"] == [], (
        "the source project's figures survived the save: %r in %r" % (s["staleExtras"],
                                                                     s["computed"]))
    assert s["computedKeys"] == ["full_bid", "lump_sum", "polish_sf", "price_per_sf"], (
        "computed_bid carries keys this page did not write: %r" % s["computedKeys"])
    assert s["fullBidKeys"] == ["remodel_tax", "sales_tax", "total_base_bid"], (
        "full_bid carries keys this page did not write: %r" % s["fullBidKeys"])
    assert s["staleSfGone"], "polish_sf still holds the source project's area"


@needs_node
def test_two_rapid_edits_send_one_save(ran):
    """Debounced on 600ms, like the calculator's and the intake form's — a save per keystroke is a
    request per keystroke against a draft row somebody else may be reading.

    Mutation: `setTimeout` without the `clearTimeout` above it. Two edits, two saves, and the
    slower reply wins whichever order they land in."""
    s = ran["save"]
    assert s["debounced"], "the save fired without the timer running"
    assert s["coalescedArmed"] == 1, "two edits armed %r timers" % s["coalescedArmed"]
    assert s["coalesced"] == 1, "two edits sent %r saves" % s["coalesced"]
    # …and the one save carries BOTH edits, rather than only the last.
    assert s["coalescedTakeoff"] == ["18000", "300", 5000], (
        "an edit was lost in the debounce window: %r" % s["coalescedTakeoff"])
    assert s["coalescedTotal"] == s["coalescedExpected"]


# ── G. migration ─────────────────────────────────────────────────────────────
@needs_node
def test_a_v1_model_becomes_v2_with_its_areas_as_measurements(ran):
    """A draft priced before the rework is `{areas: [{name, sf}], system, tooling, …}` with no
    `version`. Its measurements are the only thing worth carrying — there were no assemblies, so
    the rows come across measured and waiting for one to be picked, which blockers() then says out
    loud. `crew` was the GUYS COUNT, not a crew cost; reading it as money would multiply a saved
    estimate by eight.

    Mutation: `guys: num(old.rate)` in the v1 branch. The rows still fill in, the screen still
    looks finished, and the labor is out by a factor of ten."""
    m = ran["migration"]
    assert m["version"] == 2
    assert [r["measurement"] for r in m["takeoff"]] == [12500, 900], (
        "the v1 areas' square footage did not come across: %r" % m["takeoff"])
    assert all(r["assembly_id"] == "" for r in m["takeoff"]), (
        "migration invented an assembly for a v1 row")
    assert m["measureCells"] == ["12,500 SF", "900 SF"], (
        "the carried measurements are not on screen: %r" % m["measureCells"])
    assert m["blockers"] == ["Pick an assembly for takeoff row 1",
                            "Pick an assembly for takeoff row 2"]
    assert [[r["id"], r["guys"], r["days"], r["rate"]] for r in m["labor"]] == [
        ["polishing", 4, 3, 34], ["mockup", 2, 1, 30], ["jointfill", 5, 2, 31]], (
        "v1 labor did not come across as guys/days/rate: %r" % m["labor"])
    assert m["conditions"] == {"local": False, "hard_bid": True, "prevailing_wage": True,
                              "taxable": False, "remodel_tax": True}, (
        "the v1 job conditions were not preserved: %r" % m["conditions"])
    assert m["contingency"] == 0 and m["totals"] == {}


@needs_node
def test_the_dropped_v1_keys_are_gone(ran):
    """system / tooling / materials / added / adds / options / labour are dropped on purpose:
    assemblies replace all of them, and carrying half of them forward would price the same material
    twice.

    Mutation: `Object.assign({}, model, {version: 2, takeoff: …})` in the v1 branch. Every dropped
    key rides along, the blob grows on every save, and the next reader cannot tell which half is
    live."""
    m = ran["migration"]
    assert m["dropped"] == [], "a v1 key survived migration: %r" % m["dropped"]
    assert m["keys"] == ["conditions", "contingency", "labor", "takeoff", "totals", "version"], (
        "the v2 model's shape has changed: %r" % m["keys"])


@needs_node
def test_intake_seeds_the_first_measurement_only_when_nothing_is_measured(ran):
    """The beta intake form asks for the SF, so the calculator opens with the figure the estimator
    already gave rather than a blank. But it must never overwrite a takeoff that already measures
    something.

    Mutation: drop the `!B.takeoffSf(M.takeoff)` guard. Re-opening a finished v1 job replaces the
    warehouse's 12,500 SF with whatever intake happens to hold."""
    m = ran["migration"]
    assert m["seededFromIntake"] == 12500, (
        "intake's polish_sf overwrote a measured takeoff row: %r" % m["seededFromIntake"])
    assert m["freshFromIntake"] == 8250, (
        "a brand-new project did not pick up intake's square footage: %r" % m["freshFromIntake"])
    # A fresh model also seeds the three labor rows the template itself carries.
    assert m["freshLabor"] == [["polishing", 3, 32.2], ["mockup", 3, 32.2], ["jointfill", 3, 32.2]]


# ── H. boot ──────────────────────────────────────────────────────────────────
@needs_node
def test_nothing_is_revealed_before_the_sandbox_settles(ran):
    """The beta works on a test COPY of a real project, and this page saves within 600ms of the
    first keystroke — so it must not have a box to type in until it knows which draft it may write
    to. It must not have a priced form before the library has landed either, or the first paint
    shows every row at "—".

    (The three delegated `document.addEventListener` calls run at parse time, which is fine: there
    is nothing rendered to click yet. What is checked here is the paints.)

    Mutation: move `$("main").hidden = false` above the `await S.enterSandbox(adopt)`. On screen it
    looks identical, and a fast click writes a measurement onto a live customer bid."""
    b = ran["boot"]
    assert not b["anyPaintBeforeSandbox"], (
        "the page painted before the sandbox was even asked: %r" % b["log"])
    assert b["sandboxBeforeFirstPaint"], "the first paint beat the sandbox: %r" % b["log"]
    assert b["mainShownAfterSandbox"], "#main was revealed before the sandbox settled"
    assert b["mainShownAfterTheLibrary"], (
        "#main was revealed before the item library landed, so the first paint prices nothing")
    assert b["loadingHidden"] and b["mainShown"] and b["bidBarShown"]
    assert b["fetches"] == ["/api/library/assemblies", "/api/library/items"]
    assert b["projLine"] == "Nearman Creek · Kansas City, KS"


@needs_node
def test_a_sandbox_that_could_not_settle_never_even_fetches_the_library(ran):
    """enterSandbox returns false when it could not decide safely. Rendering the form anyway would
    offer an estimator a box to type a real customer's job into.

    Mutation: ignore the return value — `await S.enterSandbox(adopt);` on its own line."""
    s = ran["boot"]["stopped"]
    assert s["paints"] == [], "the page painted after the sandbox refused: %r" % s["paints"]
    assert s["fetches"] == [], "the library was fetched after the sandbox refused"
    assert s["mainStillHidden"], "the form was revealed after the sandbox refused"
    assert s["loadingStillShown"] and s["loadingText"].startswith("Loading"), (
        "the page did not stay on its loading message: %r" % s["loadingText"])
    assert s["saves"] == 0


@needs_node
def test_a_library_that_cannot_load_leaves_an_explanation(ran):
    """There is nothing to price against, so there is no form worth showing — but a blank page reads
    as a broken deploy. The message has to say what failed and what to do.

    Mutation: `return;` without writing to #loading. The estimator gets "Loading the item library…"
    for ever and no reason to reload."""
    f = ran["boot"]["libraryFailed"]
    assert "Couldn't load the item library" in f["loadingText"], (
        "a failed library fetch left %r on screen" % f["loadingText"])
    assert "Reload" in f["loadingText"], "the message does not say what to do about it"
    assert f["mainStillHidden"] and f["loadingStillShown"]
    assert f["panelsRendered"] == 0, "a panel was rendered with no library to price against"
    # A library that loaded but holds no assemblies is a different thing: the page opens and says so.
    e = ran["boot"]["emptyLibrary"]
    assert e["mainShown"], "an empty library hid the whole form"
    assert "no assemblies yet" in e["alert"], (
        "an empty library says nothing about why no row can be priced: %r" % e["alert"])


@needs_node
def test_the_page_prices_the_copy_the_sandbox_moved_it_onto(ran):
    """The sandbox can switch this page onto a test copy mid-boot. adopt() reassigns `state` and `M`
    together for exactly this reason — pricing the copy with the real bid's numbers still in hand is
    the same silent mix-up in the other direction.

    Mutation: `M = B.migrateModel(TW.getState().polish_estimate)` read once before enterSandbox.
    The header names the copy and the figures are the live project's."""
    c = ran["boot"]["copyAdopted"]
    assert c["projLine"] == "Nearman Creek (beta test) · Bonner Springs, KS"
    assert c["rows"] == 1, "the source project's takeoff is still on screen: %r rows" % c["rows"]
    money_is(c["cost"], c["expected"], "the copy's only takeoff row")
    # Continue and the intake link carry the draft the page SETTLED on. shared.js's _WIZARD_PATH
    # does not cover the beta pages, and the id it would have stamped is the real project's.
    assert c["continueHref"] == "/proposal-review.html?d=proj-1-beta", (
        "Continue points at the wrong draft: %r" % c["continueHref"])
    assert c["intakeHref"] == "/polish-intake.html?d=proj-1-beta"


# ── I. three steps, and the static shell ─────────────────────────────────────
@needs_node
def test_there_are_exactly_three_steps(ran):
    """Will's 2026-08-17 pass collapsed seven sub-steps into three: takeoff and material, labor,
    review. The rail, the panels and the "Step n of 3" counter all have to agree, and the counter is
    derived from the step list rather than typed — hand-written "Step 3 of 6" labels went stale the
    moment a container was split, which is what happened to the mockup.

    Mutation: a literal "of 3" in shell(). It is right until the next time a step is added."""
    sh = ran["shell"]
    assert sh["stepKeys"] == ["takeoff", "labor", "review"], sh["stepKeys"]
    assert sh["stepLabels"] == ["Takeoff and Material", "Labor", "Review"]
    assert [s["stepOf"] for s in sh["steps"]] == ["Step 1 of 3", "Step 2 of 3", "Step 3 of 3"]
    assert [s["railCount"] for s in sh["steps"]] == [3, 3, 3], (
        "the rail does not show one entry per step: %r" % sh["steps"][0]["railCount"])
    for i, s in enumerate(sh["steps"]):
        assert s["railLabels"] == sh["stepLabels"], "the rail drifted from the step list"
        assert s["current"][i] == "true" and s["current"].count("true") == 1, (
            "the rail marks %r steps as current on step %d" % (s["current"].count("true"), i))
        assert s["railPips"][i] == str(i + 1), (
            "the current step's pip shows %r rather than its number" % s["railPips"][i])
    # Back appears from step 2 on; the last step offers Continue instead of Next.
    assert sh["steps"][0]["navText"] == ["Next · Labor →"]
    assert sh["steps"][1]["navText"][0] == "← Back"
    assert "Next" not in " ".join(sh["steps"][2]["navText"])
    assert sh["units"] == ["SF", "LF"]


@needs_node
def test_the_assembly_datalist_is_filled_from_the_library(ran):
    """The box is a searchable `list=` input, not a <select>: the library is going to get long, and
    a `list=` input matches anywhere in the name, which is how somebody who remembers "grind" finds
    the assembly.

    Mutation: renderDatalist() called before the fetch resolves. The input is then a plain text box
    with no suggestions, and only a name typed exactly right resolves."""
    d = ran["datalist"]
    assert d["options"] == d["expected"], (
        "the datalist is not the library's assemblies: %r" % d["options"])
    assert d["pickerIsAList"], "the assembly box is not wired to #dl-assemblies"
    assert d["pickerIsNotASelect"], "the assembly picker became a <select>"


@needs_node
def test_nothing_on_screen_says_labour_or_crew(ran):
    """Hanz: "All labour should be renamed to 'Labor'." And "Crew" went with it — the column is
    Guys.

    SCOPED DELIBERATELY. The word may legitimately appear in code comments quoting the history of
    this rework (polish-bid-core.js documents the v1 `labour` key and why `crew` was a head count),
    so this looks at two things only: every string the page actually RENDERED across all three steps
    plus its boot messages, collected by the harness; and polish-estimate.html with its comments and
    its <style> block stripped. A comment is not user-visible; a rendered string is.

    Mutation: "Add a labour line" on the add button, or a "Crew" heading over the Guys column."""
    w = ran["words"]
    assert w["renderedChars"] > 5000, (
        "the rendered-output sample is too small to be checking anything: %r chars"
        % w["renderedChars"])
    assert w["renderedHits"] == [], "the page renders the word: %r" % w["renderedHits"]
    assert w["markupHits"] == [], "the markup carries the word: %r" % w["markupHits"]


# ── the static shell. Legitimately source-level: facts about <head> and <nav>. ──
def test_the_page_carries_no_inline_script(html):
    """The CSP refuses inline <script> and onclick=, and the refusal is silent — the page renders
    and then nothing works, which reads exactly like a logic bug."""
    for chunk in html.split("<script")[1:]:
        head, _, body = chunk.partition(">")
        if "src=" in head:
            continue
        assert not body.split("</script>")[0].strip(), "inline <script> block"
    assert "onclick=" not in html.lower()


def test_the_page_loads_no_formula_engine_and_the_modules_in_order(html):
    """HyperFormula and the whole workbook load are gone: this page prices itself now.

    The order is load-bearing and it fails silently. polish-estimate.js reads `window.TWPolishBid`,
    `window.TWLib` and `window.TWPolishSandbox` at PARSE time, so any of them loaded after it is
    `undefined`, and the first thing that touches it throws while the page sits on its loading
    message for ever.

    Mutation: move /js/polish-bid-core.js below /js/polish-estimate.js."""
    markup = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert "hyperformula" not in markup.lower(), "the beta calculator loads a formula engine again"
    assert "xl-core.js" not in markup, "the beta calculator loads the workbook helpers again"
    srcs = re.findall(r'<script[^>]*src="([^"]+)"', markup)
    assert srcs == ["https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.0",
                    "/auth.js", "/shared.js",
                    "/js/library-core.js", "/js/polish-bid-core.js", "/js/polish-sandbox.js",
                    "/js/polish-estimate.js"], (
        "the page's script list has changed: %r" % srcs)


def test_the_step_row_says_where_you_are(html):
    """Four pills, Estimate current, and step 1 pointing at the BETA intake form rather than the
    live one — the conditions moved there when the calculator dropped to three steps."""
    nav = html[html.index('<nav class="steps">'):html.index("</nav>")]
    assert 'href="/polish-intake.html">1 · Intake' in nav, (
        "step 1 does not point at the beta intake form")
    assert '<span class="on">2 · Estimate</span>' in nav, "the Estimate pill is not the current page"
    assert 'href="/proposal-review.html">3 · Proposal' in nav
    assert 'href="/done.html">4 · Files' in nav
    assert nav.count("<a ") == 3, "an unexpected number of links in the step row"


def test_there_is_a_datalist_for_the_assemblies(html):
    """renderDatalist() is null-guarded, so a missing container is not a crash — it is an assembly
    box that silently stops suggesting anything."""
    assert '<datalist id="dl-assemblies">' in html
    assert 'id="loading"' in html and 'id="sandbox-note"' in html, (
        "enterSandbox reports into #loading and #sandbox-note; without them the page would sit "
        "blank with no explanation")


def test_the_page_holds_no_rate_of_its_own(js):
    """Every percentage belongs to polish-bid-core.js, which is pinned to Kyle's workbook by
    tests/test_polish_markup_parity.py. A rate copied into this file is a second opinion waiting to
    drift from the pin, and nothing would fail when it did.

    Read past the comments, which quote the sheet's own rates on purpose."""
    body = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    for rate in ("0.02", "0.05", "0.12", "0.027", "0.16", "0.09475", "6500", "15000", "22500",
                 "32500", "32.2", "32.20"):
        assert rate not in body, "%r looks like a rate copied out of polish-bid-core" % rate
    assert "B.RATES" in js, "the page does not read the pinned rates at all"


# ── the beta runs beside the old page, not instead of it ──────────────────────
def test_the_old_estimate_review_still_exists_and_is_untouched_as_a_route():
    """Hanz chose a standalone beta so a polish bid can be priced both ways and compared."""
    assert (FRONTEND / "estimate-review.html").exists()
    index_js = (FRONTEND / "js" / "index.js").read_text(encoding="utf-8")
    assert "/estimate-review.html" in index_js, (
        "intake was re-routed to the beta; the old path must stay the default while it is a beta")


def test_nothing_is_advertised_above_the_estimate_grid():
    """Estimate Review IS the spreadsheet, so the spreadsheet gets the viewport.

    A polish-beta banner used to sit above the grid — roughly 60px of pink, on the one screen
    where the estimator is reading rows of numbers. Hanz, 2026-08-07: "I can barely see the
    sheet. The Estimate sheet is supposed to be the majority viewport."

    The beta is reached from the sidebar instead (Polish Estimate · BETA), which is where the
    Item Library and the Info Sheet announce themselves too. This test is here so the next
    feature that wants a launch moment does not take it from the grid.
    """
    html = (FRONTEND / "estimate-review.html").read_text(encoding="utf-8")
    body = html[html.index("<main>"):]
    banner = re.search(r'<(div|section|aside)[^>]*\bid="[^"]*(banner|promo|announce|beta)[^"]*"',
                       body, re.I)
    assert not banner, (
        "something is advertising itself above the grid again: %s" % (banner and banner.group(0)))

    review = (FRONTEND / "js" / "estimate-review.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in review.splitlines() if not l.strip().startswith("//"))
    assert "polish-beta-banner" not in code, "the removed banner is still being unhidden"


def test_the_sidebar_entry_is_marked_beta_and_has_its_own_glyph():
    """The sidebar door opens the beta at its INTAKE, not at pricing.

    It used to open /polish-estimate.html, which was right while the beta's step 2 held the job
    conditions itself. The 2026-08-17 rework moved those five switches onto the beta intake, so a
    door into step 2 now starts an estimator pricing before the things that change the price have
    been seen — and on a project with no name or bid date. The mid-flow door on Estimate Review
    still goes straight to /polish-estimate.html, because there the project already exists.
    """
    auth = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    assert 'navItem("/polish-intake.html"' in auth, (
        "the sidebar no longer opens the beta at its first step")
    i = auth.index('navItem("/polish-intake.html"')
    assert "BETA" in auth[i:i + 120]
    glyphs = re.findall(r'navItem\("[^"]+", "([^"]+)"', auth)
    assert len(glyphs) == len(set(glyphs)), "two sidebar items share a glyph: %s" % glyphs
