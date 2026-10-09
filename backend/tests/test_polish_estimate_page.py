"""The BETA polish calculator, executed out of the real frontend/js/polish-estimate.js.

WHAT CHANGED, AND WHY EVERY ASSERTION HERE RUNS THE PAGE.

2026-08-17: the beta dropped from seven HyperFormula-driven sub-steps to three self-pricing ones.
The workbook is gone from this screen. Will asked for a takeoff whose rows are ASSEMBLIES out of the
Items & Assemblies library, labor lines an estimator can add, and the markup chain shown as its own
reviewable block — none of which the Polish worksheet has a cell for. So the page prices itself, and
the connection to Kyle's file is kept a different way: bid-model.js transcribes his markup
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
sandbox module, the DOM and the clock are stubbed. bid-model.js and library-core.js are the
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
    and bid-model.js says the same of `per_sf`. The cost box has to agree with them.

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
    assert lab["headings"] == ["Guys", "Days", "Rate", "Cost"], (
        "the labor fields changed: %r" % lab["headings"])
    # And the hours row is headed differently, which is the whole reason the step is cards now:
    # Travel's middle number is drive-time HOURS, priced without the eight-hour day.
    assert lab["travelHeadings"] == ["Guys", "Hours", "Rate", "Cost"], (
        "Travel no longer reads as an hours row: %r" % lab["travelHeadings"])


@needs_node
def test_each_labor_task_is_its_own_card(ran):
    """The sheet heads every task separately — `Labor: Guys | Days | Rate`, then `Mock-Up:`, then
    `Joint Filler:`, then `Travel: Guys | HOURS` — rather than running them as one table under one
    header, and the step now reads the same way.

    It is not decoration. One shared header row cannot say that Travel's middle column means
    something different from the three above it, and that is exactly the thing an estimator has to
    notice before typing a number into it."""
    lab = ran["labor"]
    assert lab["cardCount"] == 3, (
        "one card per labor row: %r" % lab["cardCount"])
    assert lab["tableGone"], "the labor step still renders a <table>"


@needs_node
def test_the_travel_guys_figure_follows_the_tasks_above_it_until_somebody_disagrees(ran):
    """Polish A44 derives Travel's Guys from the rows above it, so it moves as days get typed
    rather than waiting to be copied across by hand.

    AND THE KEYSTROKE IS THE DISAGREEMENT. Typing in the box is what leaves auto — asking somebody
    to find a control first, to then be allowed to type the number they already have in mind, is a
    worse trade than noticing. Once left, the figure stops following the tasks above; the way back
    is to clear the box (there is no switch any more; see the clearing tests below)."""
    t = ran["travelGuys"]
    assert t["seeded"] == 16.5, "3x5 + 3x0.5 man-days: %r" % t["seeded"]
    assert t["afterCrewEdit"] == 13.5, (
        "the derived figure did not follow a task above it: %r" % t["afterCrewEdit"])
    assert t["boxShowsIt"] not in ("", "None"), (
        "the box sits empty next to a row that is being priced off the figure")
    assert t["afterTyping"] == {"guys": "7", "auto": False}, (
        "typing in the box did not take it off auto: %r" % t["afterTyping"])
    assert t["stickyAfterCrewMoves"] == "7", (
        "a hand-typed figure was overwritten when a task above it changed: %r"
        % t["stickyAfterCrewMoves"])
    assert t["afterBackToAuto"] == {"guys": 28.5, "auto": True}, (
        "clearing the box did not resume following the tasks above: %r" % t["afterBackToAuto"])


@needs_node
def test_the_derived_guys_figure_repaints_on_screen_and_not_only_in_the_model(ran):
    """THE SCREEN MUST NOT DISAGREE WITH ITSELF, and for one build it did.

    Typing into a field takes the `changed(false)` path, which repaints the computed TEXT — costs,
    totals, hints — and leaves the inputs alone, because until Travel arrived no input on this page
    held a figure the page itself owned. So `syncAutoGuys` moved Travel's man-days to 16.5 in the
    model, the cost cell repainted off 16.5, and the Guys box went on showing the 1.5 it had been
    rendered with.

    Every test passed: the model was right, the cost was right, the arithmetic was right. What was
    wrong was only visible in a browser — a box reading 1.5 next to a cost worked out from 16.5,
    with no way for an estimator to tell which number the bid used. A live pass read it as the guys
    figure being dropped from the formula and called it a pricing bug, which is the reasonable
    conclusion from what was on screen.

    Mutation: drop the `[data-auto]` repaint from repaintNumbers. The cost stays right and this is
    the only thing that goes red."""
    t = ran["travelLiveRepaint"]
    assert t["seededBox"] == "1.5", (
        "a fresh draft's only days are the mock-up's half: %r" % t["seededBox"])
    assert t["modelAfterCrewEdit"] == 16.5, "3x5 + 3x0.5 did not reach the model"
    assert t["boxAfterCrewEdit"] == "16.5", (
        "the box still reads the figure it was rendered with, while the cost beside it is worked "
        "out from a different one: %r" % t["boxAfterCrewEdit"])
    # Hours blank means the row is not used yet, whatever its guys says.
    assert t["costAfterCrewEdit"] == "$0"
    # And with hours typed, the row prices off the derived figure the box is now showing: 16.5
    # man-days x 2 hours x $33 = $1,089. NOT x8, which would read $8,712.
    assert t["costWithHours"] == "$1,089", (
        "travel priced off something other than the figure on screen: %r" % t["costWithHours"])
    assert t["expectedWithHours"] == 1089
    assert t["modelWithHours"]["guys"] == 16.5


@needs_node
def test_travel_dims_on_a_local_job_and_is_still_typeable(ran):
    """The intake toggle's own words are "Local job. Under 70 miles. Off means travel and lodging
    get added" — so on a local job, an UNTOUCHED Travel row is not expected, and the card says so.

    DIMMED, NOT DISABLED, NOT HIDDEN. `.sw.inert`'s convention and its reasoning: say plainly that
    an input is not affecting the price rather than disabling it and losing what somebody set. A
    local job that does need drive time must not send an estimator back to a different screen to
    record it, and a row that vanished would take their typed hours with it. The house rule keeps
    a real `disabled` at .38-.5 and never dims a live control by opacity alone, so nothing here
    carries `disabled`.

    Presentation only: the dimming must not reach laborCost, laborTotal or blockers."""
    t = ran["travelLocal"]
    assert t["dimmed"], "a local job does not dim an untouched travel card"
    assert t["saysWhy"], "the card dims without saying why"
    assert t["noDisabledAttr"], "a dimmed travel card must not disable its own inputs"
    assert t["typedAnyway"] == "3", (
        "typing into a dimmed travel card did not land: %r" % t["typedAnyway"])
    assert t["costWasZeroWhileUnused"], "an unused travel row charged something"
    # guys x 3 hours x $33 on top of the crew's $1,584 — priced per hour, and priced at all, on a
    # job the page had just called local. `guys` reads the harness's OWN derived figure rather
    # than a hardcoded 6, so this cannot pass by two numbers coincidentally agreeing.
    assert t["costAfterTyping"] == (3 * 2 * 33 * 8) + (t["derivedGuys"] * 3 * 33), (
        "a dimmed row that was typed into did not reach the total: %r" % t["costAfterTyping"])
    assert t["undimmedWhenAway"], "an out-of-town job dimmed travel anyway"


@needs_node
def test_travel_undims_live_the_moment_you_type_in_it(ran):
    """A browser pass found the Travel card staying dim while actively being typed into — the old
    rule was `hours && local`, with no notion of touched-vs-untouched. Typing in EITHER Guys or
    Hours is the estimator saying "we need this anyway", so either one lifts the dim, live, not
    only after some later full re-render.

    Mutation-tested: this is the one test in the module that would still pass if the
    `repaintNumbers` class-toggle block were deleted entirely, UNLESS it reads the live DOM node
    rather than a string snapshot — the stub's `className` setter never touches `innerHTML`."""
    t = ran["travelLocal"]
    assert t["classBeforeTyping"] == "tk lab inert", (
        "the untouched card did not start dimmed: %r" % t["classBeforeTyping"])
    assert t["classAfterTypingHours"] == "tk lab", (
        "typing Hours did not lift the dim live: %r" % t["classAfterTypingHours"])
    assert t["classAfterTypingGuys"] == "tk lab", (
        "typing Guys did not lift the dim: %r" % t["classAfterTypingGuys"])
    # Clearing the one field that means "we're using this" is "we aren't, after all" — a
    # deliberate flicker, not an oversight.
    assert t["classAfterClearingHours"] == "tk lab inert", (
        "backspacing Hours back to empty did not re-dim the card: %r"
        % t["classAfterClearingHours"])
    # The other half of the rule: a row already switched to manual (guys typed over) must not dim
    # even with hours still blank — "touched" is not the same fact as "hours filled in".
    assert t["notDimmedWhenAlreadyManual"], (
        "a row already taken off auto dimmed anyway, with no hours typed")


@needs_node
def test_there_is_no_type_my_own_switch_on_the_labor_step(ran):
    """Hanz, 2026-10-07: "remove the Type my own toggle button because technically we can edit
    it, and retain the Included button" -- for the estimate, and the labor.

    The Guys and the Lodging / Per Diem boxes are plain inputs; a control that asks permission
    to type into them is a second way to do what the box already does. Gone from every card on
    the step, Travel's included, markup and handlers both. The Included slider is a different
    control and must still be on the card.

    Mutation: put the switch back in laborCard or travelCard and `words` / the data-attribute
    flags go red."""
    n = ran["labor"]["noTypeMyOwn"]
    for key in ("words", "labManual", "labAuto", "trvManual", "trvAuto", "noLabsw"):
        assert n[key], "the Type my own switch is still rendered (%s)" % key
    assert n["includedOnTravelCard"], "the Included slider left the Travel card"
    assert ran["labor"]["noToggleOnCrewRows"]
    assert ran["labor"]["linkishGone"], "the old underlined-link markup is still being rendered"


@needs_node
def test_the_hint_says_whether_the_figure_is_typed_or_the_man_days(ran):
    """With no switch to read, the line under the box is what says which mode it is in.

    Mutation: put the old 'Man-days on the road.' wording back."""
    h = ran["labor"]["hintsAndIncluded"]
    assert h["autoHint"] == "Man-days from the tasks above."
    assert h["typedHint"] == "Typed by you. Clear it to use the man-days from the tasks above."
    # Included still toggles, and does not disturb the Guys mode.
    assert h["onBefore"] is True and h["afterOff"]["enabled"] is False
    assert h["afterOff"]["guys_auto"] is False, "Included changed the Guys mode"
    assert h["onAgain"] is True


@needs_node
def test_clearing_the_guys_box_returns_it_to_the_man_days_on_change_not_on_input(ran):
    """Going back to auto is CLEARING THE BOX, committed on change (blur / Enter).

    On input it would fight typing: "1", backspace, "2" passes through an empty box, the figure
    would snap back to the man-days and the card rebuild under the caret. So an empty box
    mid-typing stays typed; only the commit hands it back. Whitespace counts as empty, and the
    cost afterwards is the one the man-days price on a never-touched row.

    Mutation: revert on input instead of change and `midBackspace` goes red; drop the change
    branch and `afterBackToAuto` goes red."""
    t = ran["travelGuys"]
    c = ran["travelClear"]
    assert c["midBackspace"]["auto"] is False and c["midBackspace"]["guys"] == "", (
        "an empty box on input already went back to auto: %r" % c["midBackspace"])
    assert c["afterRetype"] == {"guys": "2", "auto": False}, (
        "retyping after a backspace did not land: %r" % c["afterRetype"])
    assert t["afterBackToAuto"] == {"guys": 28.5, "auto": True}
    assert c["clearedBox"] == "28.5", "the box does not show the man-days: %r" % c["clearedBox"]
    assert c["clearedHint"], "the hint did not go back to the auto wording"
    assert c["clearRebuilds"] == 0, (
        "clearing the box rebuilt the Labor panel %d time(s): the element the estimator just "
        "tabbed or clicked into is destroyed and the next click or keystroke is lost"
        % c["clearRebuilds"])
    assert c["costAuto"] == c["costFresh"] != c["costTyped"], (
        "cleared cost %r, never-touched cost %r, typed cost %r"
        % (c["costAuto"], c["costFresh"], c["costTyped"]))


@needs_node
def test_clearing_lodging_or_per_diem_returns_it_to_the_man_days(ran):
    """The same rule on the Lodging / Per Diem quantity, plus the hints and no switch there.

    Mutation: drop the data-trv branch of the clearing rule and `backToAuto` stays typed."""
    t = ran["travelCosts"]
    assert t["midClearLodging"]["qty_auto"] is False, "empty on input went back to auto"
    assert t["backToAuto"]["qty_auto"] is True and t["backToAuto"]["qty"] == 16.5
    assert t["clearedLodgingBox"] == "16.5"
    assert t["lodgeClearRebuilds"] == 0, "clearing Lodging rebuilt the panel and dropped focus"
    assert t["clearedLodgingCost"] == "$1,155"
    assert t["lodgingHints"]["auto"] and t["lodgingHints"]["noTypeMyOwn"]
    assert t["typedHintLodging"], "the typed hint is not the new wording"


@needs_node
def test_a_saved_typed_row_still_reads_as_typed_and_prices_the_same(ran):
    """A bid saved with guys_auto false (before this change, through the switch or by typing)
    reopens as typed, prices off the typed number, and a change event carrying the same number
    is not a clear."""
    s = ran["savedTypedRow"]
    assert s["typedHint"] and s["auto"] is False
    assert s["box"] == "6" and s["guys"] == 6
    assert s["cost"] == "$%d" % s["expected"], s["cost"]
    assert s["afterSameChange"] is False


@needs_node
def test_adding_a_labor_line_prices_from_its_own_values(ran):
    """Will asked for labor lines an estimator can add — the worksheet's eight rows were the reason
    the old page could not. The new row has to be editable and has to price from what was typed
    INTO IT, not from a sibling.

    Mutation: `newLaborRow()` returning a fixed id. Two added rows then share an id, and the next
    thing that keys off it (a save, a delete) touches the wrong one."""
    lab = ran["labor"]
    # 3, not 2: migrateModel() backfills the Travel row (#491) onto the fixture's saved two rows
    # at boot, so the add lands after [Polishing, Mock-up, Travel], at count 4.
    assert lab["afterAdd"]["count"] == 4, "the add button did not append a line"
    assert lab["newRowLabel"] == "Densify", "the new row's own text box does not reach the model"
    money_is(lab["newRowCost"], lab["newRowExpected"], "the added line")
    assert lab["newRowCost"] == "$1,920"
    assert lab["row0StillAnchored"] == "$3,864", (
        "adding a line moved an existing line's cost to %r" % lab["row0StillAnchored"])
    money_is(lab["totalAfterAdd"], lab["totalAfterAddExpected"], "labor total after the add")


@needs_node
def test_deleting_a_labor_line_removes_the_one_that_was_asked_for(ran):
    """Index 1 of [Polishing, Mock-up, Travel, Densify] is the mock-up — Travel is the row
    migrateModel() backfills (#491) onto the fixture's saved two rows before the page ever
    renders. Deleting the wrong line is the quietest possible data loss: the table still looks
    full.

    Mutation: `M.labor.splice(i, 1)` where i comes from `data-del-lab` on the row above, or a
    `splice(i)` with no count — which truncates everything from there down."""
    lab = ran["labor"]
    assert lab["afterDelete"] == ["Polishing", "Travel Labor", "Densify"], (
        "the delete took the wrong line: %r" % lab["afterDelete"])
    assert lab["afterDeleteCells"] == 3, "the table still renders a cell for the deleted line"
    # The survivors keep their own money after the row between them went.
    assert lab["afterDeleteCosts"] == ["$3,864", "$1,920"], (
        "the rows below the deleted one did not keep their own costs: %r" % lab["afterDeleteCosts"])


@needs_node
def test_the_last_row_cannot_be_deleted_away_to_nothing(ran):
    """At one line the ✕ is not offered — and the guard behind it holds anyway when the button the
    page rendered a moment ago is pressed again. An empty table has no box to type in and no way
    back to one.

    Mutation: drop `if (M.labor.length <= 1) return;`. The labor step renders an empty table (or,
    as it once did, refills it with an unnamed "Task" card, which can no longer be made at all)."""
    lab = ran["labor"]
    assert lab["atOneRow"]["count"] == 1
    assert lab["atOneRow"]["deleteOffered"] == 0, (
        "a ✕ is still offered on the only remaining labor line")
    assert lab["afterDeletingTheLast"]["count"] == 1, (
        "the labor table was emptied: %r" % lab["afterDeletingTheLast"])
    assert lab["afterDeletingTheLast"]["cells"] == 1, "no labor row is rendered any more"
    assert lab["afterDeletingTheLast"]["labels"] == ["Densify"], (
        "the last row was replaced by something else: %r" % lab["afterDeletingTheLast"]["labels"])
    # Same guard on the takeoff side, where the row is what the whole bid is measured on.
    t = lab["takeoffNeverEmpty"]
    assert t["count"] == 1 and t["cells"] == 1, "the takeoff was deleted away to nothing: %r" % t
    assert t["row"].get("assembly_id") == "a5", (
        "the takeoff's last row was refilled with a blank one instead of being kept: %r" % t["row"])
    # Pressing Add adds nothing by itself; ticking Densifier and pressing Add in the pop-up adds
    # ONE row already pointed at that material, priced at nothing until it is measured.
    a = lab["addedTakeoffRow"]
    assert a["beforePick"] == 3, "the add button put a row on the takeoff before anything was picked"
    assert a["count"] == 4 and a["cost"] == "—", (
        "a freshly picked takeoff row does not read as unpriced: %r" % a["cost"])
    assert a["row"]["kind"] == "item" and a["row"]["item_id"] == "i4", (
        "the picked material did not land on the row: %r" % a["row"])


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
    """Every money cell in the review block is compared with bid-model's markupChain() for the
    same model — the module that is pinned, formula string by formula string, to the Polish tab of
    Kyle's estimate_sheet_5.7.xlsx by tests/test_polish_markup_parity.py. So the screen is pinned to
    his workbook through that chain rather than by a number typed into this file.

    The fixture has prevailing wage, sales tax and the remodel tax all ON, so no line of the chain
    is dark.

    Mutation: in bid(), pass `material: roundUp(materialTotal())`. D31 already rounds up, and
    rounding twice drifts the sub-total, which then drifts GP, super/PTO, soft costs and both
    taxes — a plausible bid, tens of dollars out, on every job."""
    r = ran["review"]
    exp = r["expected"]
    for key, cell in r["rendered"]["money"].items():
        assert key in exp, "the review shows a %r line the chain does not compute" % key
        money_is(cell, exp[key], "review line %r" % key)
    # The lines Kyle's sheet has, in the order he reads them down.
    # `fees` is NOT in this list, and `contingency` never was: both are typed by the estimator
    # rather than computed, so neither has a keyed money cell to compare -- they are boxes. The
    # Fees line joined them on 2026-09-16; its own coverage is
    # test_the_fees_line_is_typed_and_marked_up_the_way_the_sheet_marks_it_up.
    # hard_bid used to be a line in this list too -- B68/D68 in Kyle's sheet, and a NEGATIVE
    # give-back on screen (ROUNDUP away from zero makes it bigger, not smaller). Removed with the
    # line itself on 2026-09-22, so there is no hard_bid money cell left to pin here or to check
    # the sign of.
    for key in ("material", "shipping", "material_total", "labor", "escalation", "burden",
                "labor_total", "sub_total", "gp", "super_pto", "soft_costs",
                "sales_tax", "remodel_tax", "taxes", "bond", "fees_and_bond", "total"):
        assert key in r["rendered"]["money"], "the review block has lost its %r line" % key
    assert r["rendered"]["persf"] == r["expectedPerSf"], (
        "the price per SF beside the lump sum is %r, not %r"
        % (r["rendered"]["persf"], r["expectedPerSf"]))


@needs_node
def test_the_percentage_column_is_the_chains_own_rates(ran):
    """Three of the rates move with the job — the GP band with the sub-total, and the two taxes
    with their toggles. hard_bid's own discount used to be a fourth, moving with the sub-total
    and the Local flag; removed with the line on 2026-09-22. They are rendered from the chain's
    own output, not from RATES.

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
    materials happen to price at nothing is then marked off, which tells the estimator to flip a
    switch that is already on."""
    o = ran["review"]["off"]
    for key in ("sales_tax", "remodel_tax"):
        assert dollars(o["rendered"]["money"][key]) == 0, (
            "%r still charges something with its condition off: %r"
            % (key, o["rendered"]["money"][key]))
        assert o["rowClasses"][key] == "off", (
            "the %r row is not marked off: class=%r" % (key, o["rowClasses"][key]))
    assert o["rendered"]["pcts"]["sales_tax_pct"] == "0%"
    assert o["rendered"]["pcts"]["remodel_pct"] == "0%"
    # A switched-off tax row carries its own switch, showing off — it used to carry an "off · edit
    # in Intake" link instead, which is a signpost where a control belongs.
    assert o["switches"]["taxable"]["on"] is False
    assert o["switches"]["remodel_tax"]["on"] is False
    # hard_bid used to have its own row here, with a "threshold" note distinguishing OFF (says
    # nothing) from ON-but-still-zero (explains the $13,000 gate). Removed with the line itself
    # on 2026-09-22, along with the note -- no other condition has a threshold shaped like it.
    # …and the whole block still agrees with the chain for that model.
    for key, cell in o["rendered"]["money"].items():
        money_is(cell, o["expected"][key], "review line %r with the taxes off" % key)
    # With the two taxes off, and only then, the escalation line is dark too (prevailing wage off).
    assert dollars(o["rendered"]["money"]["escalation"]) == 0


@needs_node
def test_each_cost_card_runs_from_a_subtotal_to_a_total(ran):
    """Settled with Hanz over three passes on 2026-09-15/16, looking at the live screen.

    Each card carries two figures and they were previously "Materials" and "Material Subtotal",
    which said nothing about how the two related. They are now the RUNNING figure and the CLOSING
    one: Material Subtotal is the takeoff lines added up, then shipping, then Material Total ends
    the card. Labor the same: Labor Subtotal is the rows added up, then escalation and burden,
    then Labor Total. Hanz, on seeing both words side by side: "Material Subtotal should be Total
    and the material inside the sheet that's not bold should have the subtotal."

    The markup block that follows then opens on a plain "Subtotal" — it was "Sub-total costs",
    the odd spelling out of three rows that are all the same kind of thing.

    ORDER IS THE CLAIM, not merely presence. A swap would leave both words on screen and both
    attached to the wrong number, which no arithmetic assertion in this file would catch — every
    figure would still be correct, and the screen would still be lying about which is which.

    Mutation: swap either pair. The totals are unchanged, the words are all still there, and this
    is the only test that goes red."""
    assert ran["review"]["labelOrder"] == [
        "Material Subtotal", "Material Total",
        "Labor Subtotal", "Labor Total",
        "<td>Subtotal</td>",
    ], "the subtotal/total pairs are out of order or renamed: %r" % ran["review"]["labelOrder"]
    # The bold row that closes each card is the TOTAL, and the markup block's own two totals keep
    # the plain word — pinned so a later "make it consistent" sweep does not undo the distinction.
    assert ran["review"]["totalRowLabels"] == [
        "Material Total", "Labor Total", "Hotel and Per Diem Total", "Total taxes",
        "Total fees + bond"], (
        "the bold closing rows are not the totals: %r" % ran["review"]["totalRowLabels"])


# ── E2. the Review step answers its own questions ────────────────────────────
@needs_node
def test_every_condition_review_talks_about_is_a_real_switch_here(ran):
    """Hanz, 2026-09-15: "any condition toggle present in BOTH Intake and Review should become a
    real, clickable toggle in Review."

    Review named five conditions and could set none of them — Sales tax and Remodel tax carried an
    "off · edit in Intake" link, Hard bid and Labor escalation carried a bare "off"/"prevailing
    wage off", and Bond carried nothing at all. An estimator reading the markup block and spotting
    a wrong flag had to leave the page, flip it, and come back. hard_bid itself is gone since
    2026-09-22, so what is left to name is four conditions, not five.

    `local` is deliberately NOT here: it is an Intake toggle Review never mentions (it dims the
    Travel row on the Labor step), so it fails the "present in both" test this exists to satisfy.

    Mutation: render the label without `data-cond`. Every switch still draws, and not one of them
    does anything when clicked."""
    sw = ran["review"]["switches"]
    assert sorted(sw) == ["bond", "prevailing_wage", "remodel_tax", "taxable"], (
        "the Review step's switches are not the conditions it talks about: %r" % sorted(sw))
    for key, s in sw.items():
        assert s["hasTrack"], "%r rendered as a label with no toggle track" % key
        assert s["role"] == "switch", "%r is not announced as a switch: %r" % (key, s["role"])
        assert s["focusable"], "%r cannot be reached by keyboard at all" % key
    # The model in this fixture has all five on, so `on` and `aria-checked` are a real claim about
    # state and not a constant that would pass with the state wired backwards.
    for key, s in sw.items():
        assert s["on"] is True and s["aria"] == "true", (
            "%r shows off while the model says on: %r" % (key, s))


@needs_node
def test_clicking_a_review_switch_answers_the_question_and_reprices(ran):
    """The click goes through the page's own delegated listener, so this is the shipped path and
    not a helper called directly.

    Mutation: flip the flag without calling `changed(true)`. The model is right, the save is
    queued, and the numbers on screen still show the old answer until the estimator reloads."""
    for key, c in ran["review"]["clicks"].items():
        assert c["flipped"], "clicking the %r switch did not change the model" % key
        assert c["othersUntouched"], "clicking %r moved another condition too" % key
        assert c["queuedASave"], "the %r answer was never queued for the draft" % key
        # The switch redraws showing the NEW answer. Without this the estimator clicks, the number
        # moves, and the control still reads the way it did before.
        assert c["reRendered"]["on"] == c["expectedOn"] and (
            c["reRendered"]["aria"] == ("true" if c["expectedOn"] else "false")), (
            "the %r switch still shows the old answer after being clicked: %r"
            % (key, c["reRendered"]))
        money_is(c["totalAfter"], c["expectedAfter"]["total"],
                 "the lump sum after clicking %r" % key)


@needs_node
def test_bond_is_a_switch_that_changes_no_number(ran):
    """The one row that must NOT move when it is clicked.

    Hanz, asked directly on 2026-09-15, chose "toggle exists, still prices at 0%". `RATES.BOND` is
    a hardcoded 0 (B78 ships at zero) and there is nowhere in the beta to store a real rate, so the
    switch exists to stop the row looking permanently dead and to carry the answer — not to unlock
    a price. It must stay that way until Kyle fixes his own sheet: the workbook's bond formula
    counts sales and remodel tax TWICE in its base, so a real rate applied through it overcharges.

    Mutation: wire the switch to a nonzero rate — `bond_pct = M.conditions.bond ? 0.01 : 0`. Every
    other test in this file still passes and the bid silently grows by about 1%."""
    bond = ran["review"]["clicks"]["bond"]
    assert bond["flipped"], "the bond switch did not record the answer"
    assert bond["totalBefore"] == bond["totalAfter"], (
        "turning Bond on moved the lump sum: %r -> %r"
        % (bond["totalBefore"], bond["totalAfter"]))
    assert dollars(bond["bondMoneyAfter"]) == 0, (
        "Bond charged something once switched on: %r" % bond["bondMoneyAfter"])
    assert bond["bondPctAfter"] == "0%", (
        "the bond rate is no longer zero once switched on: %r" % bond["bondPctAfter"])
    # And the chain itself agrees — not just the rendering of it.
    assert bond["expectedAfter"]["bond"] == 0 and bond["expectedAfter"]["bond_pct"] == 0


@needs_node
def test_travel_is_listed_even_when_it_costs_nothing(ran):
    """Hanz, 2026-09-16: "Travel should show up in Review."

    Review lists a labor row only when it prices above zero, so an unfilled Travel row was invisible
    here -- the one line an estimator is most likely to have forgotten was also the only one they
    could not check.

    Travel is now always listed; every other row keeps the rule. The difference is what a zero
    MEANS on each. An empty Polishing or Joint filler row is unfinished work, and the blockers
    panel at the top of this step already names it -- repeating it here would say the same thing
    twice and put a $0 beside a line that is going to cost thousands. An empty Travel row is a
    legitimate answer, because a local job has no travel, so its zero is a DECISION. A review step
    exists to show decisions.

    THE FIXTURE IS THE ARGUMENT. Travel and Joint filler both cost exactly $0 here, and they differ
    in nothing except which one is travel -- so "travel appears" cannot pass by travel happening to
    be priced, and "the others are hidden" cannot pass by them happening to be absent.

    Mutation: drop the `&& r.id !== "travel"` guard. Travel disappears again and every other
    assertion in this file still passes. Mutate it the other way -- list every row -- and Joint
    filler reappears at $0 beside the blocker that already names it."""
    z = ran["review"]["zeroTravel"]
    assert z["travelCost"] == 0 and z["jointFillerCost"] == 0, (
        "the fixture no longer isolates the rule: travel=%r joint filler=%r"
        % (z["travelCost"], z["jointFillerCost"]))
    assert "Travel Labor" in z["labels"], (
        "an unpriced Travel row is still missing from Review: %r" % z["labels"])
    assert "Joint filler" not in z["labels"], (
        "an unpriced non-travel row was listed: %r" % z["labels"])
    # And the priced row beside them is unaffected -- the change is about zeros, not about order.
    assert z["labels"][0] == "Polishing" and z["labels"][1] == "Travel Labor", (
        "the labor rows are out of order: %r" % z["labels"])


@needs_node
def test_the_fees_line_is_typed_and_marked_up_the_way_the_sheet_marks_it_up(ran):
    """Hanz, 2026-09-16: "Fees + Textura should be an editable field in Review."

    D77 is `=ROUNDUP(B77*C77,0)` and Kyle ships both factors blank, so the line has always read
    $0 with nothing to click. It is now a typed box, the same shape as Contingency -- the workbook
    leaves those cells open, and a line an estimator cannot fill in is one they have to remember
    to add somewhere else.

    THE SURPRISING HALF, which is why it is measured rather than eyeballed: $800 of fees does NOT
    raise the bid by $800. D77 sits inside GP's own divisor (D67), and inside the bases of
    super/PTO (D69), soft costs (D70) and the remodel tax (D75) -- so it compounds. On this
    fixture $800 moves the total by $1,545, of which $430 is GP alone. That is Kyle's column doing
    what it does, not a defect, and an estimator who checks the arithmetic will see the difference
    and need it to be deliberate.

    Mutation: `var fees = roundUp(num(input.fees))` -> `roundUp(RATES.FEES)`. The box still takes
    a number and still saves it; the bid simply ignores it. Every other test in this file passes.
    """
    f = ran["review"]["fees"]
    assert f["model"] == "800", "the typed fee never reached the model: %r" % f["model"]
    assert f["noRebuild"], "typing a fee rebuilt the review panel and would drop the caret"
    # The box seeds from the model, so a reload shows what was typed rather than an empty field.
    assert f["inputValue"] == "0", "the fees box does not render the model's own figure"
    # A fresh model and an older draft both start at the sheet's own zero, never undefined.
    assert f["freshSeed"] == 0 and f["backfilled"] == 0, (
        "fees is not seeded from the workbook's blank: fresh=%r backfilled=%r"
        % (f["freshSeed"], f["backfilled"]))
    # Every line the fee feeds moves, and each lands on the chain's own figure.
    for key in ("gp", "super_pto", "soft_costs", "remodel_tax", "total"):
        assert f["before"][key] != f["after"]["money"][key], (
            "%r did not move when a fee was typed: still %r" % (key, f["before"][key]))
        money_is(f["after"]["money"][key], f["expected"][key], "%r with a fee" % key)
    # THE COMPOUNDING ITSELF. A fee that only added itself would leave this equal to 800.
    moved = dollars(f["after"]["money"]["total"]) - dollars(f["before"]["total"])
    assert moved > 800, (
        "an $800 fee moved the bid by %r -- D77 is no longer inside the markup bases" % moved)
    assert f["expected"]["fees"] == 800, "the chain did not take the typed figure as the fee"


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
def test_a_takeoff_row_can_be_one_material_rather_than_an_assembly(ran):
    """Hanz: "there should also be add material row not assemblies only."

    Not everything an estimate buys is a system. A pallet of patch, a box of blades, one drum of
    densifier: making somebody build a one-line assembly to put a single product on a bid is
    ceremony, and the assembly it leaves behind is a system that does not exist.

    `kind` IS ON THE ROW rather than inferred from item_id. A material row that has not been
    pointed at anything yet has an empty item_id, and inferring from that alone would redraw it as
    an assembly row the moment somebody cleared the field, taking their measurement and coverage
    with it.

    THE ROW IS NOT BORN A MATERIAL any more, since 2026-09-23: one button adds a row that has not
    decided anything, and pointing it at a material is what makes it one. The rest of this test is
    unchanged, because what a material row IS did not change -- only how it gets here.

    Mutation: have setPick write item_id without writing `kind`."""
    m = ran["materialRow"]
    assert m["seededKind"] == "new", (
        "the add button pre-decided the row's kind instead of leaving it to the pick: %r"
        % m["seeded"])
    assert m["isItemKind"], "the added row is not marked as a material row"
    assert m["saysMaterial"], "a material row is indistinguishable from an assembly row on screen"
    assert m["cardClass"] == "tk mat", (
        "the redrawn card did not take the material row's own class: %r" % m["cardClass"])
    assert m["hasCoverageField"], "a material row has no coverage field, so it cannot be priced"
    assert m["resolvedId"] == "i4", (
        "typing a material name did not resolve it to a library item: %r" % m["resolvedId"])
    assert m["assemblyRowsUnchanged"], "adding a material row disturbed the assembly rows"


@needs_node
def test_a_material_row_prices_through_the_librarys_own_engine(ran):
    """THE MONEY, and it is checked against library-core rather than a number typed into this file.

    A material row is one `priceLine` call -- the same path a line inside an assembly takes, which
    is the whole reason this fits without a second engine. Coverage, waste and roundup all behave
    as they do inside an assembly because it is literally the same function.

    THE TWO FIGURES DIFFER, which is what makes this more than a tautology. Both sides call
    priceLine, so agreeing proves only that the page calls it; the library's own coverage gives
    $1,100 and a coverage typed on the row gives $2,100, so a page that ignored the row's box, or
    passed the wrong area, cannot produce both.

    Mutation: in priceMaterialRow, stop swapping the typed coverage onto a COPY of the item and
    price against ITEMS unconditionally instead, and the typed figure collapses back to the
    library one -- see test_a_typed_coverage_never_reaches_the_library_item below for the other
    half of that same mutation (it would also leak the typed figure onto every other row)."""
    m = ran["materialRow"]
    assert m["costWithLibraryCoverage"] == "$1,100", (
        "the row did not price off the item's own coverage: %r" % m["costWithLibraryCoverage"])
    assert m["costWithTypedCoverage"] == "$2,100", (
        "a coverage typed on the row did not reach the engine: %r" % m["costWithTypedCoverage"])
    assert m["costWithLibraryCoverage"] != m["costWithTypedCoverage"], (
        "both coverages priced the same, so the row's own box changes nothing")


@needs_node
def test_a_typed_coverage_never_reaches_the_library_item(ran):
    """Hanz, 2026-09-30: the coverage box on a material row is THIS ESTIMATE'S OWN OVERRIDE, not a
    second way to edit the material. Coverage, waste and roundup all moved onto the material on
    2026-09-22 -- priceLine no longer reads a line's coverage at all -- so the only way a typed
    figure can still win on this one row is for the page to price against a COPY of the item with
    the coverage swapped in, never the item itself.

    TWO INDEPENDENT SIGNS OF A MUTATION, either one enough on its own:
      * the item's own coverage, read back after the typed row, must still be the library figure
        (1,000), not the 500 that was typed into the row;
      * a SECOND row on the same material, added afterwards and left blank, must price at the
        library's own $1,100 -- not the $2,100 the first row's override would produce if it had
        leaked into the shared item.

    Mutation: swap the coverage onto the item found in ITEMS instead of a copy (e.g. `item.coverage
    = cov` before calling priceLine), and both of these flip: itemCoverageAfterOverride reads 500,
    and the second, untouched row prices at $2,100 instead of $1,100."""
    m = ran["materialRow"]
    assert m["itemCoverageBeforeOverride"] == 1000, (
        "the fixture's own Densifier coverage moved, so this test cannot tell before from after: "
        "%r" % m["itemCoverageBeforeOverride"])
    assert m["itemCoverageAfterOverride"] == m["itemCoverageBeforeOverride"], (
        "typing a coverage on the row wrote it back onto the library item: %r vs %r"
        % (m["itemCoverageAfterOverride"], m["itemCoverageBeforeOverride"]))
    assert m["secondRowBlankCoverageCost"] == m["costWithLibraryCoverage"] == "$1,100", (
        "a second, blank row on the same material priced at %r after the first row's override -- "
        "the override leaked off the row and onto every row pointing at that item"
        % m["secondRowBlankCoverageCost"])


@needs_node
def test_a_material_row_does_not_adopt_the_items_purchase_unit(ran):
    """An assembly declares the unit it is MEASURED in, so picking one can legitimately switch the
    row to LF. An item's unit is the unit it is BOUGHT in -- gallons, kits, pails -- which has
    nothing to do with how the floor is measured.

    Copying it across would set a 10,000 SF area to "Pail" and then price against it, which is the
    kind of wrong that looks like a typo and reads as a number.

    Mutation: adopt `item.unit` in setMaterial the way setAssembly adopts the assembly's."""
    assert ran["materialRow"]["unitStayedSF"], (
        "picking a material overwrote the row's unit with the pack it is bought in")


@needs_node
def test_one_control_adds_a_row_and_it_starts_undecided(ran):
    """Hanz, 2026-09-23, looking at the two dashed buttons under the last row: "These two buttons
    should be combined to one and then it should just auto categorize based off the item or
    assemblie we want to add. Also that button should be at the top and make it more visible."

    The two-button version made the estimator answer, before searching, a question they could only
    answer after searching -- and answering it wrong quietly halved the library their search box
    was allowed to see. So the row now starts as neither kind.

    AN UNDECIDED ROW IS STILL A ROW: it measures, it deletes, and it reads as unpriced rather than
    as free. What it does NOT have is a Coverage box, because coverage belongs to a material and
    nobody has said this is one.

    Mutation: push the old `{assembly_id: "", assembly_name: ""}` row from the click handler. The
    row is then an assembly row before anybody has typed, which is the bug in miniature."""
    a = ran["addControl"]
    p = ran["pendingRow"]
    assert a["addButtons"] == 1 and not a["oldMaterialButton"], (
        "there is not exactly one add control on the takeoff step")
    assert a["label"] == "Add assembly or material", (
        "the add button does not say what it adds: %r" % a["label"])
    assert a["aboveTheRows"], "the add button is still below the rows it adds"
    assert a["isThePrimaryButton"] and not a["dashedGhost"], (
        "the add button is not the page's own primary button")
    assert p["seeded"] == {"kind": "new", "pick_name": "", "measurement": "", "unit": "SF"}, (
        "an added row does not open undecided: %r" % p["seeded"])
    assert p["searchable"] and p["measurable"] and p["deletable"], (
        "an undecided row is missing one of the things every row can do: %r" % p)
    assert not p["hasCoverage"], (
        "an undecided row already offers a coverage box, which only a material has")
    assert p["cost"] == "—", "a brand-new row reads as free rather than as unpriced"
    assert p["mark"] == "new", "an undecided row is not marked as one: %r" % p["mark"]
    assert "Items & Assemblies" in p["hint"], (
        "the hint under a new row does not say where to search: %r" % p["hint"])


@needs_node
def test_picking_a_material_turns_the_row_into_one_without_rebuilding_the_panel(ran):
    """THE AUTO-CATEGORISING HALF of Hanz's one button, and the reason it is safe to do live.

    A material's card is not an assembly's -- it carries a Coverage field and a fifth column -- so
    the pick that decides the kind has to redraw the card. It must NOT redraw the panel: `change`
    fires as the estimator tabs into Measurement, and a panel rebuild at that moment destroys the
    box they have just tabbed into and drops the caret on <body>. That bug shipped once already;
    test_leaving_the_assembly_field_does_not_destroy_the_box_you_tabbed_into pins the other half.

    So: exactly one innerHTML write, on the card, with the card's own node surviving. And the row
    prices through library-core afterwards, because a row that looks right and prices wrong is
    worse than one that looks wrong.

    Mutation: `changed(true)` instead of repaintRow(i) in the pick branch of the input handler --
    the coverage box still appears, and the panel rebuild count goes from 0 to 1."""
    a = ran["autoCategorise"]
    assert a["kind"] == "item" and a["row"]["item_id"] == "i4", (
        "typing a material name did not make the row a material row: %r" % a["row"])
    assert a["coverageAppeared"], "the coverage box did not appear when the row became a material"
    assert a["labelNow"] == "Material", (
        "the field still calls itself something else: %r" % a["labelNow"])
    assert a["markGone"], "the row is still marked undecided after it decided"
    assert not a["panelRebuilt"], (
        "the whole panel was rebuilt to show one row's new field, which is what takes the caret "
        "out of the box being typed in")
    assert a["cardRedrawn"] == 1 and a["sameCardNode"], (
        "the row card was not redrawn in place: %r" % a)
    money_is(a["cost"], a["expectedCost"], "a row that categorised itself")
    assert a["unitStayedSF"] == "SF", (
        "the row adopted the pack the material is bought in as its measurement unit")


@needs_node
def test_changing_a_rows_kind_lets_go_of_the_other_kinds_fields(ran):
    """A leftover item_id would decide the row for ever, because rowKind reads it first: an
    assembly row still carrying the id of the material it used to be draws as a material and
    prices as one. So crossing the line is explicit and clears what it leaves behind -- coverage
    included, since an assembly keeps coverage on its own lines in the library.

    Mutation: make becomeKind additive (drop the `delete`s). The row keeps item_id, rowKind keeps
    answering "item", and the assembly it now names never prices."""
    f = ran["flipToAssembly"]
    assert f["kind"] == "asm" and f["row"]["assembly_id"] == "a2", (
        "an assembly name did not take the row back across: %r" % f["row"])
    assert "item_id" not in f["row"] and "item_name" not in f["row"], (
        "the row is still carrying the material it used to be: %r" % f["row"])
    assert "coverage" not in f["row"], (
        "a material's coverage survived onto an assembly row, where nothing reads it: %r"
        % f["row"])
    assert f["coverageGone"], "the coverage box is still on screen for an assembly row"
    assert f["unitAdopted"] == "LF", "the row did not adopt the assembly's own unit"


@needs_node
def test_clearing_the_name_does_not_take_the_row_back_to_undecided(ran):
    """The rule the two-button version already had, kept whole now that one field does both jobs:
    the kind changes on a resolved PICK and never on a clear.

    Somebody who blanks the name to retype it has not said the row is no longer a material. If
    clearing reset the kind, the Coverage box would vanish mid-edit and take the coverage they
    typed with it, along with the measurement's meaning.

    Mutation: have setPick fall back to "new" when nothing resolves. The coverage box disappears
    the moment the field is emptied."""
    c = ran["clearedMaterial"]
    assert c["kind"] == "item", "clearing the name flipped the row back to undecided"
    assert c["row"]["measurement"] == "2000" and c["row"]["coverage"] == "500", (
        "clearing the name took the estimator's own figures with it: %r" % c["row"])
    assert c["row"]["item_id"] == "", "the cleared name left the material id behind"
    assert c["coverageBoxStayed"], "the coverage box vanished when the name was cleared"


@needs_node
def test_a_name_that_is_both_an_item_and_an_assembly_is_never_guessed(ran):
    """THE GUARD THE OLD SPLIT LISTS WERE RIGHT ABOUT, kept one step later.

    "Grout Compound - Test" and "Plastic - Test" each exist as an item AND an assembly in the live
    library today: different ids, identical names, different money. Merging the lists makes it
    possible to resolve one to the other silently, which is precisely what the note above the old
    renderDatalist warned about. So a row that has not decided what it is holds what was typed,
    prices NOTHING, and asks -- with enough of each candidate on the button to choose by.

    The two answers are checked against different engines and come to different figures ($92.40
    off priceLine, $199.39 off priceAssembly), so a page that quietly picked one of them cannot
    pass both halves.

    A row that already has a kind is not asked: it keeps what it is.

    Mutation: in setPick, resolve `hit.item` before the both-match branch. The row silently becomes
    a material and the question is never put."""
    a = ran["ambiguous"]
    assert a["kind"] == "new", "an ambiguous name resolved the row's kind by guessing"
    assert a["row"]["pick_name"] == "Grout Compound", (
        "the typed name was not kept while the question was open: %r" % a["row"])
    assert a["cost"] == "—", "an undecided row priced itself against one of two candidates"
    assert a["offered"] == ["item", "asm"], (
        "both candidates were not offered: %r" % a["offered"])
    assert "Two things in the library are called that" in a["asked"], (
        "the row did not say why it is waiting: %r" % a["asked"])
    assert "$46.20" in a["asked"] and "1 item line" in a["asked"], (
        "the two candidates are not distinguishable on their buttons: %r" % a["asked"])
    assert a["mark"] == "pick one", "the card does not show that it is waiting on a person"

    mat = a["afterChoosingMaterial"]
    assert mat["kind"] == "item" and mat["row"]["item_id"] == "i5", (
        "choosing Material did not resolve the row to the item: %r" % mat["row"])
    assert mat["stillAsking"] == 0, "the question is still on screen after it was answered"
    money_is(mat["cost"], mat["expected"], "the material half of an ambiguous name")

    asm = a["afterChoosingAssembly"]
    assert asm["kind"] == "asm" and asm["row"]["assembly_id"] == "a6", (
        "choosing Assembly did not resolve the row to the assembly: %r" % asm["row"])
    money_is(asm["cost"], asm["expected"], "the assembly half of an ambiguous name")
    assert mat["cost"] != asm["cost"], (
        "both answers priced the same, so this fixture cannot tell a wrong resolution from a "
        "right one")

    settled = a["settledRowIsNotAsked"]
    assert settled["kind"] == "asm" and settled["assemblyId"] == "a6", (
        "a row that was already an assembly did not keep being one: %r" % settled)
    assert settled["asked"] == 0, (
        "a row that already knows what it is was asked to choose again")


@needs_node
def test_a_bid_made_entirely_of_materials_is_a_finished_bid(ran):
    """A takeoff row has been able to be one material rather than an assembly since 2026-09-19, and
    three places went on reading `assembly_id` as though it were the only way a row can be picked:
    the rail's takeoff pip, the Review step's blocker list, and the Review table's own row labels.

    So a bid made of materials priced correctly, showed its money everywhere, and still told the
    estimator it had nothing picked -- a grey pip, "Pick an assembly for takeoff row 1", and
    "(no assembly picked)" printed beside the row's own cost. One button makes material rows the
    ordinary case, so this stops being a corner.

    Mutation: put `!!r.assembly_id` back in either stepStatus or bid-model's blockers, or
    read assembly_name alone in reviewPanel."""
    m = ran["materialOnly"]
    assert m["pip"] == "ok", (
        "a picked, measured material row leaves the takeoff step looking untouched: %r" % m["pip"])
    assert m["blockers"] == [], (
        "a finished material-only bid is still listed as unfinished: %r" % m["blockers"])
    assert m["reviewPip"] == "ok", "the review step never goes green on a material-only bid"
    assert "Densifier" in m["names"], (
        "the Review table does not list the material row by name: %r" % m["names"])
    assert not any("no assembly picked" in n for n in m["names"]), (
        "a fully priced material row is printed as though nothing was picked: %r" % m["names"])


@needs_node
def test_the_three_that_moved_render_as_switches_on_the_takeoff_step(ran):
    """THE FEATURE ITSELF, which nothing pinned until now.

    Dye, joint filler and remove-existing came off the intake form on 2026-09-16 and onto this
    step. Every test written with that change probed the MODEL and the CELLS -- and a control
    deleted from the page still writes both of those correctly from its defaults. Wrapping the
    whole `.tkconds` block in `if (false)`, removing all three switches from the product, left the
    entire file GREEN. A feature nobody can see is not a feature.

    NOT ON THE LABOR STEP. They describe material, not crew, and a switch sitting among priced
    labor cards reads as though it changes one of them.

    Mutation: delete the .tkconds block, or any one switch in it."""
    t = ran["movedToTakeoff"]["onTheTakeoffStep"]
    for key in ("joint_filler", "dye", "remove_existing_jf"):
        assert t[key]["there"], "%s does not render on the Takeoff step" % key
    assert ran["movedToTakeoff"]["notOnTheLaborStep"], (
        "the moved conditions render on the Labor step, where they read as priced labor")
    c = ran["movedToTakeoff"]["cards"]
    assert c["namesItsCell"], (
        "the cards do not name the cells they set, which is one of the things they do")


@needs_node
def test_joint_filler_and_dye_render_as_material_rows(ran):
    """WHAT HANZ ASKED FOR, IN HIS OWN TERMS: "joint filler and die should have a measurement a
    unit in a total cost and they should be a material not an assembly" (staging, 2026-09-19).

    They were already priced -- 2026-09-18 put a dollar figure beside each switch -- and that was
    not what he was pointing at. A line the bid buys has four things to say: what it is, how much
    of it, in what, and what it comes to. A switch with one number beside it can say the last of
    those and nothing else, and the estimator is then left to take the Material total on trust.
    So these two now render as `.tk mat` cards over the assembly row's own four-column `.tk-g`,
    with the same `.costbox` in the Total cost column that every row above them uses.

    THE UNIT IS THE THING THAT MAKES THIS NOT A RELABEL. Dye is bought across the area, so its
    measurement IS the area in SF. Joint filler is bought in 10 gallon KITS -- ROUNDUP(area/3500)
    of them -- so quoting 17,500 SF against a $2,500 line would misname what the money buys. The
    fixture's 17,500 SF is exactly 5 kits at $500, and the card says five kits.

    Mutation: swap joint_filler's `qty` for `B.num(area)` and its `unit` for a fixed "SF"."""
    c = ran["movedToTakeoff"]["cards"]
    jf, dy = c["jointFiller"], c["dye"]
    for name, card in (("joint filler", jf), ("dye", dy)):
        assert card["isMaterialCard"], (
            "%s is not rendered as a material card -- Hanz asked for a material, not an "
            "assembly and not a switch" % name)
        assert card["usesTheAssemblyGrid"], (
            "%s does not use the takeoff row's own column template, so its figures do not line "
            "up with the rows above it" % name)
        assert card["labels"] == ["Material", "Measurement", "Unit", "Coverage", "Total cost"], (
            "%s does not carry the four columns that were asked for: %r" % (name, card["labels"]))
    # JOINT FILLER IS BOUGHT IN KITS, and the count is the one the price was worked out from.
    assert jf["name"] == "Joint filler, 10 gal kit", jf["name"]
    assert jf["measurement"] == {"cls": "", "empty": False, "text": "5"}, (
        "17,500 SF is five kits of 3,500, and the Measurement column has to say five: %r"
        % jf["measurement"])
    assert jf["unit"]["text"] == "kits", (
        "joint filler's unit is kits, not the square feet it was derived from: %r" % jf["unit"])
    assert jf["measureHint"] == "17,500 sq ft, at one kit per 3,500, rounded up.", (
        "the kit count does not show its working, so five reads as a number from nowhere: %r"
        % jf["measureHint"])
    # DYE IS BOUGHT ACROSS THE AREA, so its measurement is the area itself.
    assert dy["name"] == "Dye, per coat", dy["name"]
    assert dy["measurement"]["text"] == "17,500", dy["measurement"]
    assert dy["unit"]["text"] == "SF", dy["unit"]
    # THE PER-UNIT HINT IS KYLE'S OWN RATE, C29 and C25, arrived at by the page rather than typed
    # into it -- which is the check that the measurement and the money agree about what is bought.
    assert jf["rate"] == "$500.00 / kit", jf["rate"]
    # DYE IS TWO COATS of Kyle's 0.14 (rows 25 and 26), and the hint says so rather than quoting
    # a $0.28 the library row -- one coat -- does not hold.
    assert dy["rate"] == "2 coats \u00d7 $0.14 / SF", dy["rate"]


@needs_node
def test_nothing_on_the_priced_condition_cards_takes_typing(ran):
    """THE HONEST HALF OF THE REDESIGN.

    A material row's Measurement is the estimator's own number. Neither of these has one: the area
    is always `B.takeoffSf(M.takeoff)` -- the same figure materialTotal() prices and divides by,
    which is what stops the Material total and the price-per-SF disagreeing about what "the area"
    is -- and the kit count is recomputed from it on every render. An `<input>` in that column
    would take keystrokes and silently throw them away, which is a worse lie than the switch-and-
    a-sentence card this replaced.

    So all four columns are `.costbox`: the page's own "a field's answer, never an input" box,
    which is exactly what the Total cost column beside them has always been. FULL CONTRAST, not
    disabled-grey -- read-only and disabled are different states, and only an absent value greys.

    Mutation: render the Measurement column as `<input class="n" ...>`."""
    c = ran["movedToTakeoff"]["cards"]
    for name in ("jointFiller", "dye"):
        assert c[name]["nothingTypeable"], (
            "%s renders an input or a select, which invites typing into a figure the page "
            "derives and would discard" % name)
        assert not c[name]["measurement"]["empty"], (
            "%s's measurement is greyed on a measured job -- a derived fact keeps full "
            "contrast, only a missing value goes grey" % name)


@needs_node
def test_the_switch_sits_where_the_row_delete_sits(ran):
    """WHERE THE ON/OFF WENT, and why it is not a fifth thing bolted onto a four-column card.

    A takeoff row's header ends with the button that takes the row out of the bid. On these two
    the switch does that same job -- off means this line is not in the takeoff -- so it takes that
    slot, after the header's right-hand summary rather than crowding in beside the tag.

    ITS LABEL NAMES THE STATE. "In the bid" is readable against both switch positions; "Include"
    would name the action and therefore describe the state being left, which is the mistake the
    labor card's old "Type my own" button made and had corrected.

    Mutation: move condSwitch back above the .tk-sub summary in condMaterialCard."""
    c = ran["movedToTakeoff"]["cards"]
    for name in ("jointFiller", "dye"):
        assert c[name]["switchAfterTheSummary"], (
            "%s's switch is not in the slot a takeoff row's remove button occupies" % name)
        assert c[name]["headerSummary"], (
            "%s's header does not summarise what is bought, which is what a takeoff row's "
            "header does" % name)
    assert ran["movedToTakeoff"]["cards"]["jointFiller"]["headerSummary"] == "5 kits"
    assert ran["movedToTakeoff"]["cards"]["dye"]["headerSummary"] == "17,500 SF"


@needs_node
def test_the_total_cost_column_keeps_the_takeoff_rows_own_convention(ran):
    """SAME BOX, SAME moneyAuto, SAME EM DASH. Confirmed rather than reinvented.

    Joint Filler ships ON and 17,500 SF is five kits at $500, so it reads $2,500. Dye ships OFF
    and gets the unpriced-row dash `rowCost()` already uses, in `.costbox.empty` -- never "$0",
    which would read as a computed answer of nothing rather than "not currently in the bid".

    Mutation: render the off state as moneyAuto(0)."""
    c = ran["movedToTakeoff"]["cards"]
    jf = c["jointFiller"]["cost"]
    assert jf == {"cls": "", "empty": False, "text": "$2,500"}, (
        "Joint Filler ships on and prices 17,500 SF at one kit per 3,500 -- the Total cost "
        "column should read $2,500, got %r" % jf)
    dy = c["dye"]["cost"]
    assert dy and dy["empty"] and dy["text"] == "\u2014", (
        "Dye ships off and must show the unpriced-row dash, not a figure: %r" % dy)


@needs_node
def test_remove_existing_is_untouched(ran):
    """THE CARD THIS CHANGE WAS TOLD TO LEAVE ALONE, pinned so a later tidy-up cannot sweep it
    into the same shape for symmetry.

    Hanz named joint filler and dye. Remove Existing is not a material and buys nothing here: it
    adds a fourth hand to the joint-filler crew and is priced on the Labor step. A Measurement and
    a Total cost on it would be inventing a purchase, and a "$0" would be a figure that is wrong.

    Mutation: give remove_existing_jf a `cost` in CONDITION_CARDS."""
    r = ran["movedToTakeoff"]["cards"]["removeExisting"]
    assert r["stillASwitchCard"], "Remove Existing was rebuilt as a material card"
    assert r["noCostBox"], (
        "Remove Existing renders a cost box, which says it priced something it did not")
    assert r["noMeasurement"], "Remove Existing grew a measurement it does not have"
    assert r["namesItsCell"] and r["saysWhereItIsPriced"], (
        "Remove Existing no longer names Polish!F29 or says where its price lives")
    # And it is the only switch-shaped card left: the other two are material rows now.
    assert ran["movedToTakeoff"]["cards"]["count"] == 1, (
        "expected one switch-shaped condition card, found %s"
        % ran["movedToTakeoff"]["cards"]["count"])


@needs_node
def test_the_priced_cards_follow_the_takeoff_area_live(ran):
    """A STALE FIGURE ON A PRICED LINE IS WORSE THAN NO FIGURE, and this one was stale.

    Every number on these cards is derived from the takeoff area, and typing a measurement takes
    `changed(false)` -- the in-place repaint, never a panel rebuild. Nothing in repaintNumbers
    knew these cards existed, so from 2026-09-18 to 2026-09-19 typing 3,000 into row 1 moved the
    Material total at the bottom of the screen while the Joint Filler line above it went on
    quoting the kits and the dollars of an area that had left the page.

    READ THROUGH THE NODES. A regex over the panel's innerHTML reports the markup from render
    time and would pass with the whole repaint block deleted.

    Mutation: delete the CONDITION_CARDS loop from repaintNumbers."""
    r = ran["condCardsRepaint"]
    assert r["noRebuild"], (
        "typing rebuilt the panel, so this proves nothing about the in-place repaint")
    assert r["before"]["jf"]["qty"] == "5" and r["before"]["jf"]["cost"] == "$2,500", r["before"]
    # 12,500 down to 3,000 leaves 8,000 SF of polished area: three kits, not five.
    a = r["after"]
    assert a["jf"]["qty"] == "3", (
        "the kit count did not follow the area down to 8,000 sq ft: %r" % a["jf"])
    assert a["jf"]["cost"] == "$1,500" and r["expectedJfCost"] == 1500, (
        "the joint-filler figure disagrees with bid-model's own jointFillerCost: %r" % a)
    assert a["jf"]["sub"] == "3 kits", a["jf"]["sub"]
    assert a["jf"]["hint"] == "8,000 sq ft, at one kit per 3,500, rounded up.", a["jf"]["hint"]
    assert a["dye"]["qty"] == "8,000" and a["dye"]["sub"] == "8,000 SF", a["dye"]


@needs_node
def test_switching_dye_on_moves_the_material_total_by_exactly_the_dye(ran):
    """THE GUARANTEE UNDER THE MARKUP, which outlived two card designs and has to outlive this one.

    Flipping the switch adds `dyeCost(area)` to the Material total and moves nothing else. The
    figure is bid-model's, not one typed into this file, so a page that quietly priced the
    dye a second time -- or priced it off a different area than the one the bid divides by -- is
    caught here rather than in a proposal.

    Mutation: add the dye into materialTotal() twice, or drop it from materialTotal()."""
    d = ran["dyeToggleMovesTheTotal"]
    delta = d["materialOn"] - d["materialOff"]
    assert abs(delta - d["expectedDelta"]) < 0.005, (
        "switching dye on moved the Material total by %s, but dyeCost(%s) is %s"
        % (delta, d["area"], d["expectedDelta"]))
    assert d["laborUnmoved"], "switching dye on moved the labor total, which it does not touch"
    # 17,500 SF x $0.14 x 2 coats (Kyle's rows 25 and 26).
    assert d["costBoxOff"] == "\u2014" and d["costBoxOn"] == "$4,900", (
        "the card's own Total cost box did not follow the switch: %r -> %r"
        % (d["costBoxOff"], d["costBoxOn"]))


@needs_node
def test_remove_existing_dims_while_joint_filler_is_off(ran):
    """The `needs` rule these carried on the intake form, kept.

    Remove-existing adds a fourth hand to the joint-filler crew, so with no joint filler there is
    no crew for it to be the fourth hand of. DIMMED, NOT HIDDEN AND NOT DISABLED -- the convention
    this page already applies to Travel on a local job. Its answer still has to reach Polish!F29
    whichever way it points, because a blank Yes/No cell is not "No" to Kyle's formulas.

    HOW THIS NEARLY PASSED WHILE BROKEN: the harness probe first closed over ONE innerHTML
    snapshot taken before the gate was exercised, so it reported the markup from before the
    re-render and the gate read as working. It gave itself away by disagreeing with itself --
    joint filler off AND remove-existing undimmed in the same read, which cannot both be true. The
    probe now re-reads the panel on every call.

    Mutation: drop the third argument from the condSwitch call for remove_existing_jf."""
    m = ran["movedToTakeoff"]
    assert m["gatedWhenJointFillerOff"], (
        "remove-existing is not dimmed while joint filler is off")
    assert m["ungatedWhenJointFillerOn"], (
        "remove-existing stays dimmed after joint filler is switched on")


@needs_node
def test_the_takeoff_step_takes_its_conditions_from_the_cells(ran):
    """THE CELL WINS WHERE THERE IS ONE, the rule polish-intake.js has always applied, now applied
    here through the same shared reader.

    THIS WAS A LIVE DEFECT IN THE FIRST VERSION OF THIS CHANGE. This page built its model from
    migrateModel alone, which backfills freshModel's DEFAULT for any key a saved blob never
    stated. Every draft written before these three were model keys -- which is every draft that
    existed -- would have shown this step the defaults rather than what the estimator answered on
    intake, and the next save would have written those defaults back over the real answers in
    Polish!E25/E29/F29.

    joint_filler is the one that bites: it ships ON, so a project where somebody deliberately
    turned it off would have had it quietly turned back on and the downloaded workbook would have
    said Yes. That is a wrong document, not a wrong screen.

    A BLANK IS NOT AN ANSWER. Every save writes both literals, so an empty cell means nobody has
    answered yet and the documented default stands.

    Mutation: remove the conditionsFromCells call from adopt()."""
    h = ran["hydratedFromCells"]
    assert h["joint_filler"] is False, (
        "the cell said No and the page still shows freshModel's Yes -- the estimator's answer is "
        "about to be overwritten")
    assert h["dye"] is True, "the cell said Yes and the page did not take it"
    assert h["remove_existing_jf"] is True, "the cell said Yes and the page did not take it"
    assert h["blankLeavesTheDefault"], (
        "a blank cell overrode the model, but a blank means nobody has answered yet")


@needs_node
def test_the_save_writes_the_condition_cells_and_no_others(ran):
    """This page stopped writing state.cell_values when the workbook left it: there is no cell to
    write an assembly into. Writing a partial PRICING map would be worse than writing none —
    done.js posts the whole thing to /api/generate, and a half-filled Polish tab reads as a real
    estimate.

    THE ONE EXCEPTION, added 2026-09-15 with the Review step's switches. The five conditions'
    Yes/No cells are not a rendering of the bid; they are the contract this screen shares with the
    intake page, which reads them back on load and lets the CELL win over the model
    (polish-intake.js adoptModel: "THE CELL WINS WHERE THERE IS ONE"). That rule is only safe
    while every writer writes both places — intake's own comment says "the cell can never be the
    staler of the two" — and this page became a second writer the moment those switches shipped.

    For one commit it wrote only the model, and the bug was live: turn Sales tax off on Review,
    follow either of Review's own links to Intake (remodelSource()'s "pick a county", or the Labor
    step's "Change it on the intake step"), and the old answer came back — then intake's next save
    made the revert permanent. A silently reverted `taxable` moves the bid by 9.475% of materials.

    Mutation: drop the `cell_values` line from saveSoon. This goes red, and so does
    test_a_condition_answered_on_review_survives_a_trip_to_intake.

    Mutation the other way: write the takeoff or pricing cells here too. `cellValueKeys` grows and
    this goes red — which is the half of the old rule that still holds.

    THE RESIDUAL HAZARD, stated rather than asserted away. The payload is
    `Object.assign({}, TW.getState(), {…})`, so a map a draft ALREADY carries — from the old
    seven-step beta, which did write Polish!* cells — rides through untouched. Generating that
    project would fill the worksheet from the old beta's figures while this screen shows the new
    ones. Clearing a stale one would be an improvement and would still pass."""
    # SEVEN CONDITIONS' CELLS NOW, EIGHT KEYS, and nothing else. local carries a Polish mirror
    # (two keys); prevailing_wage, taxable and remodel_tax are formulas on the Polish tab and must
    # NOT be written there. hard_bid was an eighth condition and a ninth/tenth key, Epoxy!B5 and
    # Polish!B5 -- removed with the line itself on 2026-09-22. Kyle's own `=IF(B5="yes",...)`
    # reads a cell nobody ever writes the same way it reads "No", so there is nothing to write in
    # its place; see the note over CONDITION_CELLS in bid-model.js.
    #
    # E25/E29/F29 joined on 2026-09-16, when dye, joint filler and remove-existing moved off the
    # intake form onto the Takeoff step. Their cells did not change and neither did their
    # literals -- only which screen asks the question. They were written by polish-intake.js's own
    # `carry` loop before, from exactly one page; they go through the shared writer now because
    # two screens can answer them.
    #
    # THIRTEEN CELLS SINCE PHASE 7 (js/work-types.js), and the five new ones are the whole review: a polish
    # job writes exactly the cells the live intake writes for a polish job, because both come out of the
    # one conditions table. TAXABLE now reaches Leveling!B6 and the two Gyp B8 cells, which are independent
    # literals that nothing wrote, so a tax-exempt option on a v2 bid kept charging 9.475%. RENOVATION's
    # two B10 cells are written too, "New" while nobody has answered: the live intake writes them for every
    # polish job, and a blank Polish!B10 is not "New" to IF(B10="New",0.05,0.15), it takes the Reno branch.
    # No price moves (test_work_types.py and the chain golden), only what a save puts in the workbook cells.
    assert ran["save"]["cellValueKeys"] == [
        "Epoxy!B10", "Epoxy!B4", "Epoxy!B6", "Epoxy!D5", "Epoxy!D6", "Gyp (FR)!B8", 'Gyp (USG 1-8")!B8',
        "Leveling!B6", "Polish!B10", "Polish!B4", "Polish!E25", "Polish!E29", "Polish!F29"], (
        "the save's worksheet cells are not exactly the conditions' a polish job is asked: %r"
        % ran["save"]["cellValueKeys"])
    # And the literals are the model's own answers. The fixture has local and taxable on, the other
    # two off, so a mapping written backwards cannot pass this.
    assert ran["save"]["cellValues"] == {
        "Epoxy!B4": "Yes", "Polish!B4": "Yes",      # local
        "Epoxy!D5": "No",                           # prevailing_wage
        "Epoxy!B6": "Yes",                          # taxable
        "Epoxy!D6": "No",                           # remodel_tax
        # Joint filler ships ON and the other two off, which is freshModel's answer and was the
        # intake toggles' answer before it. BOTH LITERALS ARE ALWAYS WRITTEN, including
        # remove_existing_jf's "No" while joint filler is on: a blank Yes/No cell is not "No" to
        # Kyle's formulas, it is whatever his IF() falls through to.
        "Polish!E25": "No",                         # dye
        # OFF SINCE 2026-09-19, and the literal is still WRITTEN rather than omitted: a blank
        # Yes/No cell is not "No" to Kyle's formulas, it is whatever his IF() falls through to.
        "Polish!E29": "No",                         # joint_filler
        "Polish!F29": "No",                         # remove_existing_jf
        # The fixture has taxable ON, so the three independent Taxable literals carry the same "Yes".
        "Leveling!B6": "Yes", 'Gyp (USG 1-8")!B8': "Yes", "Gyp (FR)!B8": "Yes",     # taxable
        # Nobody has answered Renovation, so it is "New" in both cells, never blank.
        "Epoxy!B10": "New", "Polish!B10": "New",                                    # reno
    }, "the condition literals do not match the model: %r" % (ran["save"]["cellValues"],)
    # A draft that already carried a worksheet map keeps it, and gains only those same conditions' cells.
    carried = ran["save"]["legacyCellValues"] or {}
    assert set(carried) == {"Polish!D82", "Epoxy!B4", "Epoxy!B6", "Epoxy!D5",
                            "Epoxy!D6", "Polish!B4",
                            "Polish!E25", "Polish!E29", "Polish!F29",
                            "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8", "Epoxy!B10", "Polish!B10"}, (
        "the page added a worksheet cell beyond the four conditions', or dropped a carried one: %r"
        % carried)
    assert carried["Polish!D82"] == 41000, "a cell the draft already carried was overwritten"


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


@needs_node
def test_leaving_the_page_flushes_a_pending_save_instead_of_losing_it(ran):
    """Same gap as the intake page's Fault 3, on the calculator: shared.js's own pagehide net
    (shared.js:513) only flushes a timer THIS page armed, and a takeoff number typed then left via
    the step nav inside the 600ms window was silently lost. The page now runs the save synchronously
    on pagehide and forces the network PUT via TW.flushState() rather than trusting the debounce to
    survive a tab close or step-nav click.

    Mutation: remove the pagehide handler (or its `if (!saveTimer) return;` guard so it fires a save
    from nothing) and this fails either way."""
    p = ran["pagehideFlush"]
    assert p["wired"], "polish-estimate.js registers no pagehide handler at all"
    assert p["armedBeforeLeaving"] == 1, "typing a takeoff number did not arm a timer for pagehide to catch"
    assert p["savedSynchronously"] == 1, "pagehide did not push the pending save through"
    assert p["armedAfterLeaving"] == 0, "pagehide left the 600ms timer armed behind it"
    assert p["flushedTheNetwork"] == 1, "pagehide saved locally but never called TW.flushState()"
    assert p["quietWhenNothingArmed"], (
        "leaving with nothing typed must not manufacture a save or a flush out of thin air")


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
    # Travel's 24 is DERIVED, not carried: v1 had no travel row, and its Guys column is the man-day
    # sum of the three rows beside it — 4x3 + 2x1 + 5x2. Its hours stay blank, which is the figure
    # an estimator has to supply and the one that decides whether the row is used at all.
    assert [[r["id"], r["guys"], r["days"], r["rate"]] for r in m["labor"]] == [
        ["polishing", 4, 3, 34], ["mockup", 2, 1, 30], ["jointfill", 5, 2, 31],
        ["travel", 24, "", 33]], (
        "v1 labor did not come across as guys/days/rate: %r" % m["labor"])
    # FOUR keys are backfilled, not one. A v1 draft predates bond entirely, and predates dye,
    # joint_filler and remove_existing_jf living in the model at all -- until 2026-09-16 those
    # three sat in a separate `carry` object on the intake page, deliberately outside what the
    # engine is handed. migrateModel's generic conditions loop fills each from freshModel.
    #
    # The four the draft DID state come across untouched, which is the half that matters: a
    # migration that reset a v1 job's answers would change a bid that has already been sent.
    # hard_bid was a fifth stated condition until 2026-09-22; freshModel no longer declares the
    # key, so migrateModel's whitelist drops it from an old draft the same way it would drop any
    # other stranger -- an obsolete answer, not a preserved one.
    assert m["conditions"] == {"local": False, "prevailing_wage": True,
                              "taxable": False, "remodel_tax": True, "bond": False,
                              # Not in the v1 blob, so it comes from freshModel -- which ships
                              # it off since 2026-09-19.
                              "dye": False, "joint_filler": False,
                              "remove_existing_jf": False}, (
        "the v1 job conditions were not preserved: %r" % m["conditions"])
    assert m["contingency"] == 0 and m["totals"] == {}


@needs_node
def test_the_dropped_v1_keys_are_gone(ran):
    """system / tooling / materials / added / adds / options / labor are dropped on purpose:
    assemblies replace all of them, and carrying half of them forward would price the same material
    twice.

    Mutation: `Object.assign({}, model, {version: 2, takeoff: …})` in the v1 branch. Every dropped
    key rides along, the blob grows on every save, and the next reader cannot tell which half is
    live."""
    m = ran["migration"]
    assert m["dropped"] == [], "a v1 key survived migration: %r" % m["dropped"]
    # `fees` joined the shape on 2026-09-16, when the Fees + Textura line became typeable on the
    # Review step. A v1 draft has no such figure, so migration seeds it from the sheet's own zero.
    # `travel` (Lodging and Per Diem, 2026-10-05) is the newest key: both lines OFF, so a v1 draft
    # migrates to a bid that prices no travel cost until somebody turns one on.
    assert m["keys"] == ["conditions", "contingency", "fees", "labor", "takeoff", "totals",
                         "travel", "version"], (
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
    # A fresh model also seeds the four labor rows the template itself carries. Travel's 1.5 is
    # DERIVED on adopt rather than seeded: the only crew row carrying days out of the box is the
    # mock-up's half day, so the man-days come to 3 x 0.5. Its rate is the sheet's own C44 = $33.
    assert m["freshLabor"] == [["polishing", 3, 33.0], ["mockup", 3, 33.0], ["jointfill", 3, 33.0],
                              ["travel", 1.5, 33]]


@needs_node
def test_intake_system_2_seeds_a_second_takeoff_row_and_never_over_a_measurement(ran):
    """Hanz, 2026-10-05: the beta intake carries System 1 and System 2 Polish SF, and each number
    becomes a row of the step-2 takeoff, so it is typed once and the takeoff stays the only source
    of the price. polish_2_sf used to be read by nothing.

    A system-2-only job seeds ONE row from system 2 (the number is the estimator's; which box it
    was typed in changes nothing the takeoff prices). A takeoff that already measures anything
    takes neither number.

    Mutation: make B.seedTakeoffSf ignore its second argument and the two-row case collapses to
    one row; drop its early return and the measured 5,000 SF is overwritten."""
    m = ran["migration"]
    assert m["seedTwo"] == [["", 8250, "SF"], ["", 3100, "SF"]], m["seedTwo"]
    assert m["seedOnlyTwo"] == [["", 3100, "SF"]], m["seedOnlyTwo"]
    assert m["seedMeasured"] == [["", 5000, "SF"]], m["seedMeasured"]


@needs_node
def test_opening_step_2_puts_the_takeoff_total_into_the_draft_without_an_edit(ran):
    """Review finding: seeding filled the takeoff in memory only, so with System 1 = 3,000 and
    System 2 = 2,000 the screen priced 5,000 SF while the draft still said polish_sf 3,000 and
    proposal-review printed that. The live intake's beta-continue door can also type a polish_sf
    over a takeoff that is already measured. Either way polish_sf must read the takeoff total
    after a plain open; and a draft already in line is not rewritten.

    Mutation: delete the `saveSoon()` call after the seeding block in init() and the first two
    come back as None / 3000."""
    m = ran["migration"]
    assert m["savedAfterSeedTwo"] == {"sf": 11350, "bidSf": 11350}, m["savedAfterSeedTwo"]
    assert m["savedAfterClobber"] == 5000, m["savedAfterClobber"]
    assert m["savesWhenInLine"] == 0, "a draft already in line was rewritten on open"


@needs_node
def test_seeding_never_lands_beside_an_lf_only_measurement(ran):
    """B.seedTakeoffSf's own early return, which init's SF-total guard hides: a takeoff whose only
    measurement is in LF is still somebody's work, and the old code overwrote it.

    Mutation: remove the `if (num((rows[i]||{}).measurement) > 0) return rows;` line and the LF row
    gains two SF rows."""
    assert ran["migration"]["seedOverLf"] == [["", 900, "LF"]], ran["migration"]["seedOverLf"]


@needs_node
def test_emptying_the_takeoff_does_not_reseed_a_deleted_system_2_row(ran):
    """Step 2 writes polish_sf as the takeoff total but used to leave intake's polish_2_sf alone,
    so blank both seeded rows, reopen, and B.seedTakeoffSf read the stale System 2 figure as a
    fresh measurement and put the deleted row back.

    Mutation: delete the `polish_2_sf: ""` line from saveSoon (or the pagehide save) in
    polish-estimate.js and emptiedDraft2 stays 3100 and emptiedReopen holds a 3100 SF row."""
    m = ran["migration"]
    assert m["emptiedSave"] == {"sf": 0, "sf2": ""}, m["emptiedSave"]
    assert m["emptiedDraft2"] == "", m["emptiedDraft2"]
    assert not any(r[1] for r in m["emptiedReopen"]), (
        "a deleted row came back with a measurement: %r" % m["emptiedReopen"])


@needs_node
def test_defaults_load_into_a_new_bid_one_row_each_without_counting_the_floor_twice(ran):
    """Hanz, 2026-10-05: each favorited assembly and material becomes its own Takeoff row, measured
    with the intake SF. System 1 8,000 + System 2 2,000 = 10,000 SF.

    Loads: a1 (SF assembly, carries the area), a2 (LF assembly, measurement left BLANK, never a
    guess), i1 (material), i4 (material switched OFF: kept, grayed, measured). Does NOT load: the
    reserved dye row, an epoxy-only favorite, a non-favorite. The floor counts ONCE: only the first
    enabled SF default carries it, the rest are `same_floor`, so the area, polish_sf and the caption
    all read 10,000 -- not 30,000.

    Mutation: drop the `same_floor` marking in B.seedDefaultTakeoff and area/savedSf become 20,000;
    drop the reserved-id test and a `dye` row appears."""
    d = ran["defaultsLoad"]
    keys = [(r["a"] or r["i"], r["m"], r["u"], r["sf"], r["off"]) for r in d["rows"]]
    assert keys == [("a1", 10000, "SF", False, False), ("a2", "", "LF", False, False),
                    ("i1", 10000, "SF", True, False), ("i4", 10000, "SF", True, True)], keys
    assert d["area"] == 10000 and d["savedSf"] == 10000 and d["caption"] == "10,000 SF", d


@needs_node
def test_a_loaded_default_follows_the_library_coverage_not_a_constant(ran):
    """The addendum: a default's coverage is the MATERIAL's library coverage. i1 is 333 in this
    library (the shipped fixture says 275), the row's coverage box is left blank so it keeps
    following the library, and the row prices exactly as priceLine does at 333 over 10,000 SF.

    Mutation: seed the row with a literal coverage 275 and i1Price no longer equals i1Expected."""
    d = ran["defaultsLoad"]
    assert d["i1CoverageBox"] == "", "coverage was frozen onto the row"
    assert d["i1Price"] == d["i1Expected"] and d["i1Price"] > 0, d


@needs_node
def test_a_default_switched_off_adds_nothing_and_is_not_the_area(ran):
    """default_on false loads the row grayed (`enabled:false`): $0, outside the area. When NO
    enabled SF default exists the intake box seeds a plain area row, so the bid still has its floor
    -- and the off default is marked same_floor so flipping it on later cannot double the floor.

    Mutation: let the carrier be the first default whether or not it is on and allOffArea is 0."""
    d = ran["defaultsLoad"]
    assert d["offPrice"] == 0
    assert [(r["a"], r["m"], r["sf"], r["off"]) for r in d["allOff"]] == [
        ("a1", 5000, True, True), ("", 5000, False, False)], d["allOff"]
    assert d["allOffArea"] == 5000


@needs_node
def test_defaults_never_load_into_a_saved_bid_and_no_defaults_means_the_old_seeding(ran):
    """New bids only: a bid with anything saved keeps exactly its rows, and a library with no
    defaults gives the System 1 / System 2 rows seedTakeoffSf always did.

    Mutation: drop the conditionsUnstated gate in init() and the saved bid (blank takeoff, intake 700 SF) gains the default rows."""
    d = ran["defaultsLoad"]
    assert [(r["a"], r["m"]) for r in d["saved"]] == [("", 700)], d["saved"]
    assert [(r[1], r[2]) for r in d["none"]] == [(8250, "SF"), (3100, "SF")], d["none"]


@needs_node
def test_defaults_load_into_a_bid_minted_by_the_beta_intake(ran):
    """Reviewer find: the intake saves a model with conditions, so conditionsUnstated is false for
    every beta bid and the defaults never loaded. The gate now also accepts "labor never stated".

    Mutation: gate on conditionsUnstated alone and `minted` is the single blank/700 row."""
    d = ran["defaultsLoad"]
    assert d["mintedGateWasFalse"] is False
    keys = [(r["a"] or r["i"], r["m"], r["sf"]) for r in d["minted"]]
    assert keys == [("a1", 10000, False), ("a2", "", False), ("i1", 10000, True),
                    ("i4", 10000, True)], keys


@needs_node
def test_same_floor_rows_follow_the_carrier_and_stop_sharing_when_typed_over(ran):
    """Typing into a same_floor row counts its own number; changing the carrier drags the rows
    still sharing its number along.

    Mutation: use a plain `measurement = value` in the input handler and ownTyped area stays 10,000."""
    d = ran["defaultsLoad"]
    own = d["ownTyped"]
    assert [(r["a"] or r["i"], r["m"], r["sf"]) for r in own["rows"]][2:] == [
        ("i1", "2000", False), ("i4", 10000, True)], own
    assert own["area"] == 12000, own
    moved = d["carrierMoved"]
    assert [(r["a"] or r["i"], r["m"], r["sf"]) for r in moved["rows"]][2:] == [
        ("i1", "2000", False), ("i4", "6000", True)], moved
    assert moved["area"] == 8000, moved


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
    # The company labor rate is read for every bid (it feeds the "Default $X" line), in parallel.
    assert b["fetches"] == ["/api/markup/rules?layout=global", "/api/library/assemblies",
                            "/api/library/items"]
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
    # does not cover the beta pages, and the id it would have stamped is the real project's. The
    # intake link is remodelSource()'s "pick a county" — the last one Review builds at render time,
    # now that the switched-off rows carry their own control instead of a link back to Intake.
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
    assert sh["stepLabels"] == ["Material", "Labor", "Review"]
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
def test_the_search_offers_both_the_assemblies_and_the_materials(ran):
    """THE BUG HANZ REPORTED, 2026-09-23: "the dropdown search only pulls assemblies."

    It was never a data fault -- /api/library/items and /api/library/assemblies both return real,
    distinct rows. The row's kind was fixed when the row was created, and each kind's box was
    wired to its own list, so the half of the library you had not pre-declared was simply not
    there. One list, both collections, and each option says which one it came from.

    The box is still a searchable `list=` input rather than a <select>: the library is going to get
    long, and `list=` matches anywhere in the name, which is how somebody who remembers "grind"
    finds the assembly.

    Mutation: fill the list from ASMS only, which is exactly what the page did before, and the
    materials vanish from the box again."""
    d = ran["datalist"]
    assert d["options"] == d["expected"], (
        "the list is not both collections, deduped and sorted: %r" % d["options"])
    assert "Densifier" in d["options"] and "Polish 800 Grit" in d["options"], (
        "an item or an assembly is missing from the one list: %r" % d["options"])
    assert set(d["labels"]) <= {"Material", "Assembly", "Material or assembly"}, (
        "an option went out without saying which collection it came from: %r" % d["labels"])
    assert d["collision"] == ["Material or assembly"], (
        "the name that is in both collections is listed twice or unlabelled: %r" % d["collision"])
    assert d["caseTwins"] == 2, (
        "two assemblies differing only by case were collapsed into one option, which hides a "
        "library problem this page must not resolve")
    assert d["pickerIsAList"], "the search box is not wired to #dl-lines"
    assert d["pickerIsNotASelect"], "the picker became a <select>"


# ── dye and the joint filler kit: priced off their reserved library rows ─────────────────────
# Hanz: "joint filler and die should be library items so that we are able to edit them as well."
# Both are RESERVED library_items rows (backend/library.py's RESERVED_ITEM_IDS), edited on the
# Items tab; the page prices its two condition cards off them through priceLine (condLine) and
# falls back to jointFillerCost/dyeCost when a row is not there. All of it is the real page run
# by polish-estimate-harness.js (out.reservedItems).
SFS = ("0", "1", "3500", "3501", "12000")


@needs_node
def test_the_seeded_rows_price_every_bid_to_the_cent_as_before(ran):
    """PRICE IDENTITY, the condition this change ships on. At every area that matters -- none, one
    square foot, exactly one kit's worth, one foot over it, and a big floor -- a page holding the
    SEEDED rows, a page holding NO rows, and the shipped constants called directly all give the
    same material total, the same bid, and the same figures on both condition cards. The seed
    fixture is pinned to the schema files by test_both_schema_files_seed_the_dye_and_joint_filler
    _rows_the_engine_prices_like_the_constants below.

    Mutation: seed the kit's waste as null/5 or its roundup off (3500 and 3501 move); read the
    dye row's coverage as the divisor the wrong way round; drop the fallback in condLine (the
    `missing` column goes to $0)."""
    ident = ran["reservedItems"]["identity"]
    assert sorted(ident, key=float) == list(SFS), ident.keys()
    for sf in SFS:
        row = ident[sf]
        assert row["seeded"]["material"] == row["constants"], (
            "at %s SF the seeded rows price dye + joint filler at %r, the shipped constants at %r"
            % (sf, row["seeded"]["material"], row["constants"]))
        assert row["missing"]["material"] == row["constants"], (
            "at %s SF a page with no reserved row no longer falls back to the shipped constants: "
            "%r vs %r" % (sf, row["missing"]["material"], row["constants"]))
        assert row["seeded"]["total"] == row["missing"]["total"], (
            "at %s SF the bid differs between the seeded rows and the fallback: %r vs %r"
            % (sf, row["seeded"]["total"], row["missing"]["total"]))
        assert row["seeded"]["cards"] == row["missing"]["cards"], (
            "at %s SF the condition cards read differently off the seeded rows: %r vs %r"
            % (sf, row["seeded"]["cards"], row["missing"]["cards"]))
    # THE VECTORS ARE NOT VACUOUS: one kit at 3,500, a second at 3,501, and $0 at 0 SF.
    # Two coats of dye (Kyle's rows 25 and 26) and the kits.
    assert ident["3500"]["constants"] == pytest.approx(3500 * 0.14 * 2 + 500)
    assert ident["3501"]["constants"] == pytest.approx(3501 * 0.14 * 2 + 1000)
    assert ident["0"]["constants"] == 0


@needs_node
def test_editing_the_library_rate_changes_the_bid(ran):
    """$700 a kit and $0.50 a square foot a coat on the rows, figures that share nothing with the
    shipped $500 / $0.14: the material total is two kits at $700 plus two coats of 3,501 SF at
    $0.50, and each card quotes the rate it charged.

    Mutation: have condLine price off RATES instead of the row, or have materialTotal call
    jointFillerCost/dyeCost directly."""
    r = ran["reservedItems"]["rated"]
    assert r["material"] == pytest.approx(r["expected"]), r
    assert r["cards"]["joint_filler.rate"] == "$700.00 / kit", r["cards"]
    assert r["cards"]["dye.rate"] == "2 coats \u00d7 $0.50 / SF", r["cards"]
    assert r["cards"]["joint_filler.qty"] == "2", r["cards"]


@needs_node
def test_editing_the_kits_coverage_changes_the_kit_count(ran):
    """The kit count is the row's own coverage now, not a 3,500 in the code. The same 3,500 SF is
    one kit at the seeded coverage and four at 1,000; a 10% waste on the row buys a second kit,
    because the material rule inflates before it rounds up. The card's sentence says what the
    arithmetic did.

    Mutation: keep `a / 3500` for the kit count; drop the row's waste; hardcode the hint's 3,500."""
    r = ran["reservedItems"]
    assert r["oneKit"] == "1", r["oneKit"]
    assert r["oneKitHint"] == "3,500 sq ft, at one kit per 3,500, rounded up.", r["oneKitHint"]
    assert r["fourKits"] == "4", r["fourKits"]
    assert r["fourKitsCost"] == pytest.approx(2000), r["fourKitsCost"]
    assert r["fourKitsHint"] == "3,500 sq ft, at one kit per 1,000, rounded up.", r["fourKitsHint"]
    assert r["wastedKits"] == "2", r["wastedKits"]
    assert r["wastedHint"] == "3,500 sq ft, at one kit per 3,500 plus 10% waste, rounded up.", (
        r["wastedHint"])


@needs_node
def test_a_row_that_cannot_price_falls_back_and_off_still_charges_nothing(ran):
    """A missing row is covered by the identity test above. A row that is THERE but cannot price
    (its coverage or its cost blanked on the Items tab) must not bill $0 either: it takes the same
    shipped formula a missing row does. And a condition that is off charges nothing whatever its
    row says.

    Mutation: return p.cost from condLine whatever p.ok says; drop the `if (M.conditions.x)` gate
    in materialTotal."""
    r = ran["reservedItems"]
    assert r["blanked"]["material"] == pytest.approx(r["blanked"]["constants"]), r["blanked"]
    assert r["offMaterial"] == 0, r["offMaterial"]


def _reserved_item_seed(path):
    """The rows one schema file's library_items insert seeds, as {id: {column: value}}, plus
    where in the file the insert sits. Comments stripped first, so a seed somebody has commented
    OUT does not read as a seed (the travel-row test's own lesson)."""
    sql = re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))
    found = list(re.finditer(
        r"insert into public\.library_items\s*\(([^)]*)\)\s*values\s*(.*?)"
        r"\s*on conflict \(id\) do nothing;", sql, re.I | re.S))
    assert len(found) == 1, (
        "%s must seed library_items with exactly ONE idempotent insert, found %d"
        % (path.name, len(found)))
    m = found[0]
    cols = [c.strip() for c in m.group(1).split(",")]
    rows = {}
    for tup in re.findall(r"\(([^)]*)\)", m.group(2)):
        vals = []
        for tok in re.findall(r"\s*('(?:[^']|'')*'|[^,]+)", tup):
            tok = tok.strip()
            if tok.startswith("'"):
                vals.append(tok[1:-1].replace("''", "'"))
            elif tok.lower() in ("true", "false"):
                vals.append(tok.lower() == "true")
            elif tok.lower() == "null":
                vals.append(None)
            else:
                vals.append(float(tok))
        row = dict(zip(cols, vals))
        rows[row["id"]] = row
    return rows, m.start(), sql


@needs_node
def test_both_schema_files_seed_the_dye_and_joint_filler_rows_the_engine_prices_like_the_constants(ran):
    """THE ROWS, THE FILES AND THE ENGINE HAVE TO AGREE, and they live in four places.

    Both schema files seed the three reserved rows (DDL LANDS TWICE: prod Supabase and the staging
    Postgres are different databases), library.py refuses to delete them, library.js keeps the
    Remove button off them, and the page prices two of them. The third, remove-existing-jf
    (2026-10-01), buys nothing: its unit_cost and coverage are seeded NULL and must stay NULL, so
    a figure cannot creep into a row nothing is supposed to price off. The harness's
    RESERVED_SEED is what test_the_seeded_rows_price_every_bid_to_the_cent_as_before proves
    prices exactly like the
    shipped constants -- so requiring both files to say EXACTLY that, column for column, is what
    makes the identity a fact about the databases rather than about a fixture.

    WASTE IS A LITERAL 0, never null: a null waste reads as the 5% default and would buy 5% more of
    both. A FRESH DATABASE MUST BUILD: every column the insert names has to exist by the time the
    insert runs, so the waste/roundup/buy_qty columns are added ABOVE it.

    Mutation: seed any row differently in one file; seed waste as null; give remove-existing-jf a
    cost; move the insert above the waste_pct/roundup alters; rename an id in library.py's
    RESERVED_ITEM_IDS or library.js's RESERVED_ITEM_CONDITION."""
    import library  # noqa: E402 -- backend/ is the working directory for this suite

    backend = pathlib.Path(__file__).resolve().parents[1]
    seed = {r["id"]: r for r in ran["reservedItems"]["seed"]}
    seeded = {}
    for name in ("supabase_schema.sql", "staging/schema_pg.sql"):
        rows, at, sql = _reserved_item_seed(backend / name)
        seeded[name] = rows
        for col in ("buy_qty", "waste_pct", "roundup"):
            alter = re.search(r"alter table public\.library_items add column if not exists %s\b"
                              % col, sql, re.I)
            assert alter and alter.start() < at, (
                "%s: the library_items insert names %s before any `add column if not exists %s` "
                "above it, so a fresh database fails on this insert" % (name, col, col))
        assert set(rows) == set(seed), (name, sorted(rows))
        for rid, want in seed.items():
            got = rows[rid]
            assert set(got) == set(want), (
                "%s seeds %s with columns %r, the priced seed has %r"
                % (name, rid, sorted(got), sorted(want)))
            for col, val in want.items():
                # NULL ONLY WHERE THE PRICED SEED SAYS NULL -- remove-existing-jf's cost and
                # coverage. Anywhere else a NULL is a row that prices wrong (a null waste reads
                # as 5%).
                if val is None:
                    assert got[col] is None, "%s seeds %s.%s as %r, not NULL" % (
                        name, rid, col, got[col])
                    continue
                assert got[col] is not None, "%s seeds %s.%s as NULL" % (name, rid, col)
                if isinstance(val, bool) or isinstance(val, str):
                    assert got[col] == val, (name, rid, col, got[col], val)
                else:
                    assert got[col] == pytest.approx(val), (name, rid, col, got[col], val)
    assert seeded["supabase_schema.sql"] == seeded["staging/schema_pg.sql"], (
        "the two schema files seed DIFFERENT dye / joint filler rows, so prod and staging would "
        "price them differently")

    assert set(library.RESERVED_ITEM_IDS) == set(seed), library.RESERVED_ITEM_IDS
    # THE THIRD ROW BUYS NOTHING, in both files: no cost and no coverage to price from.
    assert seed["remove-existing-jf"]["unit_cost"] is None
    assert seed["remove-existing-jf"]["coverage"] is None
    # THE PAGE'S MAP OF RESERVED ROWS IS THE TABLE'S, since Phase 7: library.js reads each condition's
    # `item_id` off js/work-types.js (reservedItems), and the Takeoff cards on this page read the same
    # ids, so it is the table's ids that are held to the seed here, through the cards the page really built.
    assert set(ran["cards"]["reserved"]) == set(seed), ran["cards"]["reserved"]
    js = (FRONTEND / "js" / "library.js").read_text(encoding="utf-8")
    assert "var RESERVED_ITEM_CONDITION = WT.reservedItems();" in js, (
        "library.js no longer reads its reserved rows off the vocabulary")


@needs_node
def test_the_reserved_rows_are_never_a_takeoff_row_and_the_card_uses_the_live_name(ran):
    """Each is already priced by its own condition card, so neither may become an ordinary takeoff
    row: it is left out of the picker's list AND a name typed out in full resolves to nothing,
    either of which would charge the same material twice. Renaming the row on the Items tab
    renames the card.

    Mutation: drop the RESERVED_ITEM_IDS filter from renderDatalist or itemByName; render the
    card's material from a literal."""
    r = ran["reservedItems"]
    assert r["dyeNotInPicker"], "\"Dye, per coat\" is offered in the takeoff row picker"
    assert r["jointFillerNotInPicker"], (
        "\"Joint filler, 10 gal kit\" is offered in the takeoff row picker")
    assert r["removeExistingNotInPicker"], (
        "\"Remove existing joint filler\" is offered in the takeoff row picker")
    assert r["ordinaryItemsStillListed"], "an ordinary material vanished from the picker too"
    assert r["typedNameResolvesToNothing"], (
        "typing a reserved row's name resolves a takeoff row to it")
    assert r["ordinaryNameStillResolves"], "an ordinary material no longer resolves by name"
    # Typed into a row that is ALREADY a material (setPick -> setMaterial), not just looked up.
    assert r["typedPick"]["dye"] not in ("dye", "joint-filler-kit"), (
        "typing 'Dye, per coat' into a material row turned it into a second dye charge")
    assert r["typedPick"]["kit"] not in ("dye", "joint-filler-kit"), (
        "typing the kit's name into a material row turned it into a second joint filler charge")
    assert r["typedPick"]["rem"] not in ("remove-existing-jf",), (
        "typing 'Remove existing joint filler' into a material row picked its reserved row")
    assert r["typedPick"]["ordinary"] == "i1", "typing an ordinary material no longer resolves it"
    assert r["renamed"] and not r["notRenamedByDefault"], (
        "the joint filler card does not show the row's own name")


@needs_node
def test_nothing_on_screen_says_labour_or_crew(ran):
    """Hanz: "All labour should be renamed to 'Labor'." And "Crew" went with it — the column is
    Guys.

    THE BRITISH SPELLING IS THIS TEST'S WHOLE SUBJECT, so neither the name above nor the pattern in
    the harness's `offenders()` may be swept along by a labour->labor rename. Pointed at "labor"
    instead, it asserts the page never says the word it is supposed to say in a dozen places, and
    goes red everywhere at once — which is exactly what happened the first time this rename ran.

    SCOPED DELIBERATELY. The word may legitimately appear in code comments quoting the history of
    this rework (bid-model.js documents the v1 `labour` key and why `crew` was a head count),
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

    The order is load-bearing and it fails silently. polish-estimate.js reads `window.TWBidModel`,
    `window.TWWorkTypes` (its Takeoff cards, since Phase 7), `window.TWLib` and `window.TWPolishSandbox`
    at PARSE time, so any of them loaded after it is
    `undefined`, and the first thing that touches it throws while the page sits on its loading
    message for ever.

    Mutation: move /js/bid-model.js below /js/polish-estimate.js."""
    markup = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert "hyperformula" not in markup.lower(), "the beta calculator loads a formula engine again"
    assert "xl-core.js" not in markup, "the beta calculator loads the workbook helpers again"
    srcs = re.findall(r'<script[^>]*src="([^"]+)"', markup)
    # /js/icons.js is FIRST, ahead of auth.js: the sidebar auth.js draws asks it for every glyph
    # in the rail. See the house rule at the top of frontend/js/icons.js.
    assert srcs == ["https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.0",
                    "/js/icons.js", "/auth.js", "/shared.js", "/js/tab-memo.js",
                    "/js/library-core.js", "/js/excel-math.js", "/js/work-types.js", "/js/markup-core.js",
                    "/js/bid-profiles.js", "/js/bid-engine.js", "/js/bid-model.js",
                    "/js/polish-sandbox.js", "/js/library-picker.js", "/js/polish-estimate.js"], (
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


def test_there_is_a_datalist_for_the_search_box(html):
    """renderDatalist() is null-guarded, so a missing container is not a crash — it is a search box
    that silently stops suggesting anything.

    ONE list, not two: the pair it replaced (#dl-assemblies and #dl-items) is what made the box's
    contents depend on which button created the row."""
    assert '<datalist id="dl-lines">' in html
    assert 'id="dl-assemblies"' not in html and 'id="dl-items"' not in html, (
        "the split lists are still in the page, so something can still be wired to half the "
        "library")
    assert 'id="loading"' in html and 'id="sandbox-note"' in html, (
        "enterSandbox reports into #loading and #sandbox-note; without them the page would sit "
        "blank with no explanation")


def test_the_page_holds_no_rate_of_its_own(js):
    """Every percentage belongs to bid-model.js, which is pinned to Kyle's workbook by
    tests/test_polish_markup_parity.py. A rate copied into this file is a second opinion waiting to
    drift from the pin, and nothing would fail when it did.

    Read past the comments, which quote the sheet's own rates on purpose."""
    body = "\n".join(l for l in js.splitlines() if not l.strip().startswith("//"))
    for rate in ("0.02", "0.05", "0.12", "0.027", "0.16", "0.09475", "6500", "15000", "22500",
                 "32500", "32.2", "32.20"):
        assert rate not in body, "%r looks like a rate copied out of bid-model" % rate
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

    The beta is reached from the sidebar instead (Estimating Tool v2 · BETA), which is where the
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


@needs_node
def test_leaving_the_assembly_field_does_not_destroy_the_box_you_tabbed_into(ran):
    """FOUND IN A BROWSER, on staging, with all 43 other tests green.

    `change` on the assembly field fires when the estimator leaves it, and the ordinary way to
    leave it is Tab into Measurement. A full re-render at that moment rebuilds the row, destroys
    the field they have just tabbed into, and drops focus onto <body> — so the number they type
    next goes nowhere and nothing on screen explains why. No unit test reaches for the keyboard,
    which is why this needed a browser to see and why it is pinned here now.

    Node identity is the assertion, because an innerHTML write on #panels replaces every child
    object: if the measurement box is a different object afterwards, the caret was in the old one.

    Mutation: `changed(true)` in the assembly_name branch of the `change` handler."""
    r = ran["leavingTheAssemblyField"]
    assert r["rebuilds"] == 0, (
        "leaving the assembly field rebuilt the panel %d time(s), taking the field the estimator "
        "tabbed into with it" % r["rebuilds"])
    assert r["measurementSurvived"], (
        "the measurement box was replaced when the assembly field was left, so a caret sitting in "
        "it is now on <body> and the next keystroke is lost")
    # And the pick still lands — the repaint has to do everything the rebuild used to.
    assert r["idNow"] == r["expectedId"], "the newly typed assembly was not adopted"
    assert r["unitSyncedInPlace"] == r["expectedUnit"], (
        "the unit select still shows the previous assembly's unit")
    assert "item line" in (r["hintNow"] or ""), "the hint under the picker was not refreshed"


# ── the remodel tax uses the county's real rate ───────────────────────────────
@needs_node
def test_the_remodel_tax_uses_the_countys_real_rate_not_the_sheets_ten_percent(ran):
    """Hanz, 2026-08-18: "For the Remodel tax please use the real state tax or city tax, DONT USE
    10%".

    Kyle's workbook hardcodes 10% at B75, and that figure is not a real rate anywhere. Kansas
    charges sales tax on commercial remodel LABOR at the state rate plus the county portion only,
    which is 7.975% in Johnson County. The live estimating tool has looked the real rate up per
    county since 2026-06-02, and the beta now reads the same `county_remodel_rate` key off the
    draft, so a project priced on either screen agrees with the other.

    Mutation: drop `remodel_rate: remodelRate()` from the page's bid() call and the rate silently
    falls back to the Kansas state floor on every job, including the Johnson County ones."""
    c = ran["remodelRate"]["county"]
    assert c["pct"] == "7.975%", "a Johnson County job is not charged the county rate: %r" % c["pct"]
    assert c["pct"] == c["expectedPct"]
    # NOW $1,557 / $34,025 AS OF 2026-09-30. $1,529 held from 2026-09-19 until the library's
    # coverage/waste/roundup moved onto the material (2026-09-22): this fixture's items i2/i3/i4
    # were never given their own waste_pct, so they now correctly default to 5% instead of quietly
    # inheriting the 0% their assembly lines used to carry -- and i4 (Densifier, 5 pails needed)
    # ceiling-rounds to a whole extra pail at 5.25. That is a real, upstream, already-approved
    # engine change, not a fixture bug: it moves the sub-total, and GP, shipping and the taxes all
    # follow it, which is exactly why the figure is worth pinning rather than recomputing in the
    # test.
    assert c["money"] == "$1,557" and c["expectedMoney"] == 1557
    assert c["total"] == "$34,025" and c["expectedTotal"] == 34025, (
        "the total does not follow the county rate through the chain")
    assert c["rowNamesTheCounty"], (
        "the row does not say which county the rate came from; an estimator who knows the workbook "
        "reads this line expecting 10% and needs to see why it differs")


@needs_node
def test_with_no_county_it_falls_back_to_the_state_rate_and_says_so(ran):
    """A low answer an estimator can correct beats an invented one they might not question.

    10% is the number NOT to fall back to: it is the one figure that looks authoritative because
    it matches the sheet, while being wrong everywhere."""
    f = ran["remodelRate"]["fallback"]
    assert f["pct"] == "6.5%", "the no-county fallback is not the Kansas state rate: %r" % f["pct"]
    # NOW $1,269 AS OF 2026-09-30 -- the same coverage-on-material default-waste shift as the
    # county case above (see that test's comment), just at the state rate instead of the county's.
    assert f["money"] == "$1,269" and f["expectedMoney"] == 1269
    assert f["expectedMoney"] != f["whatTenPercentWouldBe"], (
        "the fallback charges what the sheet's 10% would have charged (%s), so this test proves "
        "nothing" % f["whatTenPercentWouldBe"])
    assert f["saysStateRate"], "the review screen does not say the state rate is standing in"
    assert f["offersToPickACounty"], "it does not tell the estimator how to get the real rate"


@needs_node
def test_a_percentage_typed_on_the_estimate_screen_beats_the_county_on_the_draft(ran):
    """One number, one source. Kyle gets the rate from the state's site for the ADDRESS:

        "we use the link within the original excel sheet to go to the website, enter the
         address, and get the tax % from there."

    So the live estimate screen lets him type it, and it overrides the county table there.
    This page reads the same draft, and its whole reason for reading `county_remodel_rate`
    is that "a project that chose its county on either screen prices the same on both". A
    typed rate has to be honoured for exactly that reason -- otherwise the beta would show
    the county's rate while the workbook it generates carried the typed one, which is the
    two-disagreeing-tables defect all over again.

    The fixture deliberately carries BOTH: Wyandotte County at 9.35% on the draft and
    7.975% typed. Asserting the county's figure separately means this cannot pass by
    accident if the two ever happened to price the same."""
    t = ran["remodelRate"]["typed"]
    assert t["pct"] == t["expectedPct"]
    assert t["money"] == t["expectedMoneyText"]
    assert t["expectedMoney"] != t["whatTheCountyWouldBe"], (
        "fixture is vacuous: the typed rate and the county rate price identically")


@needs_node
def test_a_county_rate_on_the_draft_does_not_switch_the_remodel_tax_on(ran):
    """The toggle decides WHETHER, the county decides HOW MUCH. A project that recorded its county
    for the sales-tax lookup must not acquire a remodel tax it was never marked for."""
    off = ran["remodelRate"]["toggleOff"]
    assert off["pct"] == "0%" and off["money"] == "$0", (
        "a remodel tax appeared on a job whose remodel toggle is off: %r" % off)


@needs_node
def test_a_missouri_county_is_charged_nothing_not_the_kansas_fallback(ran):
    """Missouri taxes remodel LABOR as exempt, so a Missouri county carries no remodel rate on
    purpose. That absence means "we know, and it is nothing" — not "we don't know".

    THE BUG THIS PREVENTS: reading the missing rate as unknown stands the Kansas state rate up and
    charges every Missouri remodel job a Kansas tax it does not owe. The page therefore passes an
    explicit 0 once a county is chosen, and null only while none has been.

    Mutation: `return null` instead of `return 0` in remodelRate() when state.county is set."""
    mo = ran["remodelRate"]["exemptCounty"]
    assert mo["pct"] == "0%", "a Missouri remodel job was charged %s" % mo["pct"]
    assert mo["money"] == "$0", "a Missouri remodel job was charged %s" % mo["money"]
    assert mo["whatTheFallbackWouldBe"] > 0, (
        "the Kansas fallback charges nothing here either, so this test proves nothing")
    assert mo["saysExempt"], "the review screen does not say why the remodel tax is nil"


@needs_node
def test_the_county_is_printed_as_stored_not_with_County_appended(ran):
    """`county` is stored as "Johnson County, KS" — the shape the live estimate screen's picker
    writes, which the beta intake matches so both screens keep one value. Appending " County" to
    that read "Johnson County, KS County" beside the remodel row."""
    assert not ran["remodelRate"]["county"]["doubledCountyWord"], (
        "the county name is printed with 'County' appended to a value that already contains it")


# -- the library's default labor lines ----------------------------------------
# "+ Add a labor line" on Library -> Default Items & Assemblies shipped wired to nothing, because
# nothing stored a custom labor line. public.library_labor now does, and this step is what reads
# it. Every test below BOOTS the page and RENDERS its Labor step: a gate that reads the wrong
# thing still contains the word laborUnstated, and a row that never reaches the panel is still on
# a model somebody could print. That is exactly how the dead button shipped green.
@needs_node
def test_a_brand_new_bid_opens_holding_travel_and_every_default_line(ran):
    """A default that nothing consumes is a settings screen that lies. A new estimate opens with
    the three crew rows off Kyle's Polish tab, Travel, and then every line the estimator set up
    under Items & Assemblies -- named, rendered, and editable.

    THE TABLE AND THE MODEL DISAGREE ON PURPOSE: the row is `name` in the database and `label` on
    the model. One mapping bridges them (B.libraryLaborRow), and this is the test that would see
    it come apart -- the defaults would render with blank name boxes.

    Mutation: delete the `M.labor = B.seedLibraryLabor(...)` line from init(). The page still
    opens, still prices, and every test that existed before this one still passes."""
    n = ran["laborDefaults"]["brandNew"]
    assert n["ids"] == ["polishing", "mockup", "jointfill", "travel",
                        "lab-densify", "lab-night"], (
        "a new bid did not open holding Travel AND the library's lines, in that order: %r"
        % n["ids"])
    # RENDERED, not merely on the model: these are the values in the boxes the Labor step drew.
    # TRAVEL LABOR IS DRAWN LAST, below the dividing line, with Lodging and Per Diem under it
    # (2026-10-05) -- the MODEL order above is unchanged, only where the Labor step puts the card.
    assert n["onScreen"] == ["Polishing", "Mock-up", "Joint filler", "Densify",
                             "Night shift premium", "Travel Labor"], (
        "the Labor step did not put the defaults on screen: %r" % n["onScreen"])
    assert n["costCells"] == 6, "the panel drew %r cost cells for 6 rows" % n["costCells"]
    assert n["rates"] == [33, 33, 33, 33, 40, 12.5], (
        "a default's rate did not come across as a number: %r" % n["rates"])
    # The estimator's own boxes are left for the estimator. A default says what the line is and
    # what it costs per unit, never how much of it this job needs.
    assert n["days"][4:] == ["", ""], "a default arrived with days already typed in"
    # ...with the one documented exception, which is not a typed figure at all: a default that
    # carries guys_auto gets the derived man-day sum before the first paint, exactly as Travel
    # does. Compared to Travel's own rather than to a literal, because the point is that the two
    # went through the same sync, not that today's fixture sums to any particular number.
    assert n["autoGuys"] == n["travelGuys"] and n["travelGuys"] != [""], (
        "a guys_auto default was not filled the way Travel is: %r vs %r"
        % (n["autoGuys"], n["travelGuys"]))
    # A default must not quietly put money on a bid nobody has priced yet.
    assert n["laborTotal"] == n["builtInTotal"], (
        "seeding the defaults changed the labor total before anything was typed: %r vs %r"
        % (n["laborTotal"], n["builtInTotal"]))
    assert n["mainShown"]


@needs_node
def test_a_project_that_came_through_the_beta_intake_gets_the_defaults_too(ran):
    """THE CASE THAT DECIDES WHETHER ANY OF THIS IS REACHABLE. Every beta project starts on
    polish-intake.html, whose save mints the first `polish_estimate` -- version, takeoff,
    conditions, and no labor, because labor is not that page's to state.

    Until 2026-09-17 that save stated labor anyway: migrateModel fills a missing `labor` in from
    freshModel() before handing the model back, so the first keystroke on the intake form
    persisted four crew rows nobody had been shown. That was enough to disqualify every beta
    project from its own defaults, seconds before the estimator ever reached the Labor step.

    THIS TEST OWNS THE CALCULATOR'S HALF ONLY, and its fixture is that blob written out by
    hand. The intake page's half -- that this really is what it mints -- is pinned next door by
    test_this_page_does_not_state_labor_it_has_no_screen_for, which asks the real
    B.laborUnstated() the same question about what that page actually saved. Verified: dropping
    the `delete model.labor` line from js/polish-intake.js turns that test red and leaves this one
    green, because a hand-built fixture cannot notice the other page changing.

    Mutation: delete the `M.labor = B.seedLibraryLabor(...)` line from init() -- the calculator
    stops seeding the one blob shape every beta project arrives in."""
    f = ran["laborDefaults"]["fromIntake"]
    assert f["fetched"], "a project minted by the beta intake never even asked for the defaults"
    assert f["ids"] == ["polishing", "mockup", "jointfill", "travel",
                        "lab-densify", "lab-night"], (
        "the normal flow does not get the defaults: %r" % f["ids"])
    assert f["onScreen"][-3:] == ["Densify", "Night shift premium", "Travel Labor"]


@needs_node
def test_a_saved_bid_opens_exactly_as_it_was_saved(ran):
    """THE HARD CONSTRAINT. An estimator's labor rows are their work. A bid that has been worked
    on comes back row for row, number for number, no matter what the default list says today --
    including a default they kept and then re-rated from $40 to $55.

    The defaults are not filtered out late; they are never asked for. `fetches` carries no
    /api/library/labor at all, which is the only way to tell "the gate ran" from "the gate
    happened to add nothing today".

    NOT VACUOUS: `wouldHaveAdded` seeds that same saved array with that same library list and a
    row arrives. There was something to keep out.

    Mutation: replace the gate in init() with `true` (seed unconditionally). `after` grows a fifth
    row and the estimator's $55 sits next to a $40 duplicate."""
    w = ran["laborDefaults"]["worked"]
    assert w["after"] == w["saved"], (
        "a saved bid's labor came back changed:\n saved: %r\n opened: %r"
        % (w["saved"], w["after"]))
    assert w["onScreen"] == ["Polishing", "Mock-up", "Densify", "Travel Labor"], (
        "the Labor step drew something other than the saved rows: %r" % w["onScreen"])
    assert not [u for u in w["fetches"] if "/labor" in u], (
        "a saved bid asked the server for the default labor lines: %r" % w["fetches"])
    assert len(w["wouldHaveAdded"]) > len(w["saved"]), (
        "the library holds nothing this bid is missing, so 'nothing was added' proves nothing: %r"
        % w["wouldHaveAdded"])
    # A v1 draft keeps its crew under `labour` and so has no `labor` key at all. Reading that
    # absence as "never worked on" would append the defaults to crew rows typed months ago.
    v1 = ran["laborDefaults"]["v1"]
    assert not v1["fetched"], "a v1 draft asked for the defaults"
    assert v1["ids"] == ["polishing", "mockup", "jointfill", "travel"], (
        "a v1 draft was given the library's default lines: %r" % v1["ids"])


@needs_node
def test_deleting_a_default_leaves_the_bids_already_holding_it_alone(ran):
    """Once seeded and saved, the row is the BID's. The library is not consulted about it again,
    so an admin tidying the default list cannot reach into a bid that was priced with one -- which
    would move a customer's number after it had been quoted.

    Mutation: make the seeding an intersection instead of an addition -- rebuild `M.labor` from
    the library list on every load. The kept row disappears off a saved bid the moment somebody
    deletes the default."""
    d = ran["laborDefaults"]["deleted"]
    assert "lab-densify" in d["ids"], (
        "deleting the default took it off a bid already holding it: %r" % d["ids"])
    assert d["onScreen"] == ["Polishing", "Mock-up", "Densify", "Travel Labor"]
    assert d["densifyRate"] == [55], (
        "the kept row lost the estimator's own rate: %r" % d["densifyRate"])


@needs_node
def test_a_missing_defaults_table_is_no_defaults_and_never_a_broken_step(ran):
    """public.library_labor is on STAGING and not on production, by Hanz's decision. So on prod
    today this endpoint has no table behind it, and it has to read as "no custom labor lines"
    rather than as a broken page. A new bid that opened with no Labor step at all would be far
    worse than one that opened without a default nobody has defined yet.

    Both shapes the failure arrives in are covered: the read going down, and it answering with
    something that is not a list of rows (a 404's JSON body, an { ok: false }).

    Mutation: put the labor read inside the assemblies/items Promise.all. Both cases then land on
    "Couldn't load the item library" with #main still hidden -- a blank screen on production."""
    for key in ("down", "notRows"):
        case = ran["laborDefaults"][key]
        assert case["ids"] == ["polishing", "mockup", "jointfill", "travel"], (
            "%s: the built-in rows did not survive the defaults read failing: %r"
            % (key, case["ids"]))
        assert case["mainShown"], "%s: the page never opened" % key
        assert case["alert"] == "", (
            "%s: an estimator was told something was wrong about a table that is simply not "
            "there yet: %r" % (key, case["alert"]))
    down = ran["laborDefaults"]["down"]
    assert down["loadingHidden"], "the page stayed on its loading message"
    assert down["onScreen"] == ["Polishing", "Mock-up", "Joint filler", "Travel Labor"], (
        "the Labor step came up without Travel on it: %r" % down["onScreen"])
    assert down["costCells"] == 4


@needs_node
def test_a_default_that_still_needs_numbers_says_which_one(ran):
    """A default states what the line IS and what it COSTS per unit -- never how much of it this
    job needs. So on a `days` line it arrives with a rate and two empty boxes, and blockers()
    reads a row with one or two of its three boxes empty as half-filled. That is exactly the
    treatment Polishing and Joint filler already get off Kyle's own sheet: a default the estimator
    does not need on this job is removed with the row's own x, not left sitting at nothing.

    Both ways that could go wrong are pinned. It must not block the bid WITHOUT naming the row --
    the estimator would be hunting through six rows for the empty box. And an HOURS default must
    take the same "no hours means unused" carve-out Travel does, or every local job would open
    demanding drive time it is never going to need.

    Mutation: hardcode `unit: "days"` in libraryLaborRow. The hours default stops taking Travel's
    carve-out and every new bid opens demanding numbers for a line nobody has switched on."""
    n = ran["laborDefaults"]["brandNew"]
    says = n["blockers"]
    assert "Add the guys and days for Densify" in says, (
        "a default that needs numbers does not say which row or which box: %r" % says)
    assert not [s for s in says if "Night shift" in s], (
        "an hours default did not take Travel's own 'no hours means unused' carve-out, so a bid "
        "nobody is driving to opens blocked: %r" % says)
    # …and the built-in rows are still named the way they always were, so the defaults have not
    # drowned them out.
    assert "Add the days for Polishing" in says


# ── the Takeoff conditions' company answers ───────────────────────────────────
THREE = ("joint_filler", "dye", "remove_existing_jf")


@needs_node
def test_a_brand_new_bid_opens_with_the_conditions_the_library_says(ran):
    """The three Takeoff conditions stopped being "built in" on 2026-09-18 (Hanz, twice). Their
    answers for a new bid are set on the Library page's Defaults tab, and this is the page that
    has to take them.

    EVERY STORED ANSWER IN THE FIXTURE DISAGREES WITH WHAT THE TOOL SHIPS. All three ship OFF
    since 2026-09-19 and the library says on for all three. A fixture that agreed with freshModel
    would pass just as happily against a seeder that was never wired up at all.

    Mutation: delete the `if (conditionDefaults)` block from init(). Every new bid then opens with
    the shipped literals whatever anybody sets, and the Defaults tab is decoration."""
    c = ran["conditionDefaults"]["brandNew"]
    assert c["fetched"], "a blank bid never asked for the stored answers"
    assert c["conditions"]["joint_filler"] is True, (
        "the library's 'on' did not reach a brand new bid, so the Defaults tab changes nothing")
    assert c["conditions"]["dye"] is True
    assert c["conditions"]["remove_existing_jf"] is True
    # The five answered on Intake are not this tab's to move.
    assert c["conditions"]["taxable"] is True and c["conditions"]["local"] is True


@needs_node
def test_the_reserved_rows_change_neither_the_seeded_conditions_nor_the_price(ran):
    """2026-10-01: remove-existing became a reserved library row beside dye and the joint filler
    kit (Hanz: "All 3 exactly like materials"), so the Defaults tab can list it as a material. A
    new estimate must open with EXACTLY the conditions it opened with before for the same
    condition defaults, and come to the same total, whether the three rows are in the library or
    not -- and remove-existing, on, must move no material figure and no bid figure by a cent,
    because nothing prices off its row.

    Mutation: give remove-existing's card a `cost` that reads its row, or seed conditions off the
    library rows' `favorite` instead of condition_defaults."""
    n = ran["conditionDefaults"]
    assert n["brandNewWithRows"]["conditions"] == n["brandNew"]["conditions"], (
        "the reserved rows changed which conditions a brand new bid opens with: %r vs %r"
        % (n["brandNewWithRows"]["conditions"], n["brandNew"]["conditions"]))
    assert n["brandNewWithRows"]["total"] == n["brandNewWithRows"]["totalWithoutRows"], (
        n["brandNewWithRows"])
    rem = ran["reservedItems"]["removeExisting"]
    assert rem["withRow"] == rem["withoutRow"], (
        "remove-existing's reserved row moved the bid: %r" % rem)
    assert rem["withRow"]["material"] == rem["offMaterial"], (
        "remove-existing, on, changed the material total -- it is a labor modifier, not a "
        "material: %r" % rem)


@needs_node
def test_a_bid_that_has_been_worked_on_keeps_its_own_conditions(ran):
    """THE HARD CONSTRAINT, at the page level. Hanz, verbatim: changing a default must not change
    any estimate that already exists, because an estimator's saved answers are their work.

    joint_filler is the one that bites: it SHIPS on, so a bid where somebody deliberately turned
    it off is exactly the bid a careless default would quietly turn back on -- and because
    conditionCellWrites puts all eight literals back on every save, the downloaded workbook would
    then say Yes in Polish!E29 with nothing on any screen admitting it.

    THE GATE IS OBSERVABLE, not inferred: a saved bid never even asks for the defaults, so
    `fetched` is False. And NOT VACUOUS -- `wouldHaveChanged` applies the same stored answers to
    the same migrated model and shows all three moving.

    Mutation: drop the `B.conditionsUnstated(...) ?` gate in init() and always load. Every
    reopened bid then adopts today's defaults on the next save."""
    w = ran["conditionDefaults"]["worked"]
    assert w["fetched"] is False, (
        "a bid that has been worked on asked for the condition defaults; the gate is not being "
        "asked before the read")
    for key in THREE:
        assert w["after"][key] == w["saved"][key], (
            "%s came back as %r on a saved bid that had %r"
            % (key, w["after"][key], w["saved"][key]))
    moved = [k for k in THREE if w["wouldHaveChanged"][k] != w["saved"][k]]
    assert len(moved) == 3, (
        "the stored answers agree with this bid's, so 'it came back unchanged' proves nothing -- "
        "only %r would have moved" % moved)


@needs_node
def test_a_cell_answer_still_beats_the_library_on_a_blank_bid(ran):
    """THE CELL WINS WHERE THERE IS ONE, which is why conditionsFromCells runs AFTER the seed
    rather than only in adopt().

    A project that came through the live intake has no polish_estimate at all -- exactly the blob
    conditionsUnstated calls seedable -- while the answers the estimator or the AI autofill gave
    sit in cell_values. If the seed ran last it would write a company-wide default over one of
    those, and the next save would make it permanent in Kyle's workbook.

    ALL THREE CELLS ANSWERED, not one -- exactly what a real step-1 save on the live intake screen
    leaves behind (Polish!E29=No, Polish!E25=No, Polish!F29=Yes). A fixture that answered only one
    of the three could pass against a page that seeded the other two from the library regardless
    of what their cells said.

    AND THE LIBRARY LIST IS NARROWED ON PURPOSE, which is the part that keeps this honest now that
    all three conditions SHIP OFF. joint_filler and dye have a library row saying ON against a
    cell saying "No": `False` there can only mean the cell beat the library. remove_existing_jf
    has NO library row and a cell saying "Yes": `True` there can only mean the cell was read at
    all. The first pair alone could not show that second thing -- `False` is also what a page that
    read neither the cell nor the library would produce -- and before 2026-09-19 it did not need
    to, because the shipped answer for joint_filler was the opposite of the cell's.

    Mutation: swap the two calls in init() so seedConditionDefaults runs outermost. joint_filler
    and dye come back flipped and every cell answer the estimator gave is gone."""
    c = ran["conditionDefaults"]["celled"]
    assert c["fetched"], "the library was never asked for its stored answers"
    assert c["dye"] is False, (
        "the library's 'on' was written over the 'No' already in Polish!E25")
    assert c["jointFiller"] is False, (
        "the library's 'on' was written over the 'No' already in Polish!E29")
    assert c["removeExistingJf"] is True, (
        "the 'Yes' already in Polish!F29 never reached the model, so the cells are not being "
        "read at all")


@needs_node
def test_the_defaults_table_being_absent_opens_the_bid_anyway(ran):
    """`condition_defaults` is applied to NEITHER database as of 2026-09-18, and production will
    be behind staging even after it is. A bid that refused to open over a table nobody has
    promoted would be a far worse outcome than one that opens with the answers the tool ships.

    AND SAYS NOTHING ABOUT IT. A default nobody has defined yet is not an error to report to an
    estimator mid-bid.

    Mutation: let the exception out of loadConditionDefaults. The page dies on boot on production
    the day this ships."""
    d = ran["conditionDefaults"]["down"]
    assert d["mainShown"], "the estimate did not open when the defaults read failed"
    assert d["alert"] == "", "the page reported a table nobody has promoted as an error"
    for key in THREE:
        assert d["conditions"][key] == d["shipped"][key], (
            "%s did not fall back to what the tool ships" % key)


# ── grayed until on, and only what the Defaults tab lists ─────────────────────────────────────
@needs_node
def test_condition_cards_are_grayed_until_switched_on(ran):
    """Hanz, 2026-10-01: "dont start as on staart as off in the estimating sheet but it appears as
    grayed out like travel in labor". All three start off, and an off card is drawn dimmed
    (`.tk.inert`, the class Travel's card takes on a local job) -- still clickable, nothing
    disabled. On, it is drawn at full strength.

    Mutation: drop the `inert` class from condMaterialCard or condSwitchCard."""
    g = ran["grayedUntilOn"]
    assert g["allOffGrayed"], "an off condition card is not grayed"
    assert g["dyeOnNotGrayed"], "dye switched on is still grayed"
    assert g["removeExistingOnNotGrayed"], "remove existing switched on is still grayed"
    assert g["removeExistingOffGrayedOnItsOwn"], (
        "remove existing, off with joint filler ON, is not grayed -- only its `needs` gate dims it")


@needs_node
def test_a_condition_off_the_defaults_tab_is_not_drawn_on_a_new_bid(ran):
    """"Everything that is in the defaults and labor tab in the Items and Assemblies appear as
    grayed out options that can be enabled or not." So one taken off the Defaults tab is not drawn
    on a bid made after that -- unless it is switched on, which always shows. The answer is
    snapshotted onto the bid (conditions_shown) behind conditionsUnstated, so a saved bid keeps
    every card it had.

    Mutation: drop the conditionShown filter in takeoffPanel; let conditionShown ignore an on
    answer; seed conditions_shown outside the conditionsUnstated gate."""
    g = ran["grayedUntilOn"]
    assert g["dyeHiddenWhenOffTheList"], "a card taken off the Defaults tab is still drawn"
    assert g["onAlwaysShows"], "a hidden condition that is switched on is not drawn"
    assert g["freshSnapshot"] == {"dye": False}, g["freshSnapshot"]
    assert g["freshHidesDye"], "a new bid drew the card the Defaults tab took off"
    assert g["savedBidKeepsAll"], "a saved bid lost a card because the Defaults tab changed later"
    assert g["migrated"] == {"dye": False}, g["migrated"]
    assert g["noMapStaysNoMap"], "migrateModel invented a card map for a bid that had none"
    assert g["touchedCardStays"], (
        "a hidden card that arrived ON vanished when the estimator switched it off")
    assert g["removeExistingFollowsJointFiller"], (
        "remove existing is drawn while joint filler is off the list -- no switch could un-gray it")
    assert g["seeded"] == {"dye": False}, g["seeded"]


# ── B2: coverage on the estimate, per bid ────────────────────────────────────────────────────
@needs_node
def test_every_row_kind_shows_the_library_coverage_and_prices_with_a_typed_one(ran):
    """HANZ: "In the estimate form in the beta it should pull the default coverage areas for the
    defaults." A row that arrives from the Defaults carries NO coverage of its own, so the box has
    to show the LIBRARY's figure (275 for OPF, 275 / 775 for the two lines of Polish 800 Grit --
    none of them the old 3,500 constant) and the total has to price with it. A number typed over
    it prices the bid, and the amber line directly under the box says "Default value: N"; the library item
    itself is never touched. An ASSEMBLY row gets one box per material line.

    Mutation: render the assembly row with no coverage boxes; have priceAssemblyRow ignore the
    typed figure; leave the hint at "How far one goes" when the figures differ."""
    r = ran["rowCoverage"]
    f = r["first"]
    assert f["matBox"] == ["", "275"], f["matBox"]
    assert f["matHint"] == "Blank uses the library's 275."
    assert len(f["asmBoxes"]) == 2 and 'placeholder="275"' in f["asmBoxes"][0]         and 'placeholder="775"' in f["asmBoxes"][1], f["asmBoxes"]
    assert f["matCost"] == "$1,793.04" and r["expectedFirstMat"] == pytest.approx(1793.0367)
    assert f["asmCost"] == "$10,599.98" and r["expectedFirstAsm"] == pytest.approx(10599.9771)
    m = r["matTyped"]
    assert m["cost"] == "$1,707.65" and m["expected"] == pytest.approx(1707.654)
    assert m["hint"] == "How far one goes, for this job."
    assert m["warn"] == {"text": "Default value: 275", "hidden": False}, m["warn"]
    a = r["asmTyped"]
    assert a["cost"] == "$10,258.45" and a["expected"] == pytest.approx(10258.4463), a
    assert a["hint0"] == "How far one goes, for this job."
    assert a["warn0"] == {"text": "Default value: 275", "hidden": False} and a["warn1"] == {"text": "", "hidden": True}, (a["warn0"], a["warn1"])
    assert a["hint1"] == "Blank uses the library's 775.", "an untouched line keeps the library figure"
    assert a["line_cov"] == {"0": "300"} and a["libraryUntouched"] == 275
    assert r["matBackToLib"]["hint"] == "How far one goes, for this job."
    assert r["matBackToLib"]["warn"] == {"text": "", "hidden": True}, "typing the default back must hide the warning"
    assert "Library default" not in str(r), "the old wording is gone"
    # a different assembly means different lines: the old lines' coverage must not follow
    assert r["switched"] == {"line_cov": True, "boxes": 1}, r["switched"]


@needs_node
def test_joint_filler_and_dye_cards_carry_a_per_bid_coverage_box(ran):
    """The two condition cards get the same Coverage box. The library kit is set to 2,000 (not
    3,500) so "the library's figure" and "the old constant" cannot be confused: 6,000 SF is 3
    kits at $500; typing 3,000 on THIS bid makes it 2 kits ($1,000), moves the Material total by
    exactly that, rewrites the kit sentence and says "Library default: 2000". The figure is
    stored on the bid (cond_cov) and survives a reload; a bid with none prices as before.

    Mutation: condLine reads the library coverage whatever the box says."""
    c = ran["condCoverage"]
    u, j = c["untouched"], c["libJf"]
    assert u["before"]["jfBox"] == ["", "2000"]
    assert u["after"]["jfHint"] == "Blank uses the library's 2000."
    assert u["after"]["jfCost"] == "$1,500" and u["jfKits"] == 3
    assert j["after"]["jfCost"] == "$1,000" and j["jfKits"] == 2
    assert j["after"]["jfQtyHint"] == "6,000 sq ft, at one kit per 3,000, rounded up."
    assert j["after"]["jfWarn"] == {"text": "Default value: 2000", "hidden": False}, j["after"]["jfWarn"]
    assert u["after"]["jfWarn"] == {"text": "", "hidden": True} and u["before"]["dyeWarn"] == {"text": "", "hidden": True}
    assert j["matBefore"] - j["matAfter"] == pytest.approx(500)
    assert j["savedModel"] == {"joint_filler": "3000"} and j["migrated"] == {"joint_filler": "3000"}
    assert u["savedModel"] is None
    assert c["backToLibrary"]["after"]["jfHint"] == "How far one goes, for this job."
    assert c["backToLibrary"]["after"]["jfWarn"] == {"text": "", "hidden": True}
    d = c["libDye"]
    assert d["before"]["dyeBox"] == ["", "2"] and d["after"]["dyeWarn"] == {"text": "Default value: 2", "hidden": False}
    assert d["dyeCost"] == pytest.approx(6000 / 4 * 0.2 * 2), d["dyeCost"]


# ── M. the company labor rate (Markups -> Global) ─────────────────────────────
@needs_node
def test_a_new_bid_starts_every_labor_rate_from_the_company_rate(ran):
    """The three crew rows, Travel Labor, a library row with no rate of its own and a line the
    estimator adds all open on the Global labor rate ($40 here, not the sheet's $33). A library
    row somebody re-rated ($55) keeps its own number.

    Mutation: drop `B.applyLaborRate(...)` in init() -- the crew rows stay on the hard-coded
    $33 and this fails on `polishing`. Mutation: `rate: LABOR_RATE` -> `rate: ""` in
    newLaborRow -- fails on addedRate."""
    r = ran["laborRate"]["newBid"]
    for rid in ("polishing", "mockup", "jointfill", "travel", "lab-none"):
        assert r[rid] == 40, "%s did not start from the company rate: %r" % (rid, r)
    assert r["lab-own"] == 55, "a library row with its own rate was overwritten: %r" % r
    assert ran["laborRate"]["addedRate"] == 40


@needs_node
def test_no_company_rate_means_the_shipped_33_and_nothing_breaks(ran):
    """Nothing filed, the markup read failing, and a rate switched OFF all read as the sheet's own
    $33.00. The page still opens (these builds all booted)."""
    lr = ran["laborRate"]
    for key in ("noRule", "down", "off"):
        assert lr[key]["polishing"] == 33 and lr[key]["travel"] == 33, (key, lr[key])
        assert lr[key]["lab-none"] == 33, (key, lr[key])


@needs_node
def test_a_saved_bid_keeps_its_rates_and_says_what_the_default_is(ran):
    """New bids only. The saved bid's 33 and 36 are untouched and the library defaults are never
    even asked for -- but each rate that differs from the company rate says 'Default $40.00'.

    Mutation: remove the `laborDefaults` gate around applyLaborRate -- polishing becomes 40."""
    lr = ran["laborRate"]
    assert lr["saved"] == {"polishing": 33, "mockup": 36, "travel": 33}, lr["saved"]
    assert lr["savedFetchedLaborDefaults"] is False
    assert [x["text"] for x in lr["savedDefaultLines"]] == ["Default value: $40.00"] * 3
    assert all(not x["hidden"] for x in lr["savedDefaultLines"])


@needs_node
def test_default_line_shows_only_while_the_rate_differs(ran):
    """Hidden on every row of a new bid (a library row's own $55 is ITS default, G1), shown the
    moment the estimator types 45 over a row, hidden again when they type the default back (the
    in-place repaint, not a rebuild)."""
    lr = ran["laborRate"]
    # Render order since 2026-10-05: Travel Labor is drawn last, under the Travel dividing line.
    assert [x["hidden"] for x in lr["newBidLines"]] == [True] * 6
    assert lr["typedOver"]["hidden"] is False
    assert lr["typedBack"]["hidden"] is True


@needs_node
def test_travel_labor_with_its_own_library_rate_shows_no_false_default_warning(ran):
    """G1. Travel's library row says $41, the company rate is $40: a new bid opens Travel at 41 and
    NOTHING warns (a row's default is the rate it was filled with). Typing 50 over it warns against
    $41.00, not the company $40.

    Mutation: remove `B.stampRateDefaults(...)` in init() -- Travel warns 'Default value: $40.00'
    with nothing typed."""
    t = ran["laborRate"]["travelOwn"]
    assert t["rate"] == 41
    assert all(x["hidden"] for x in t["lines"]), t["lines"]
    assert t["typedOver"]["hidden"] is False
    assert t["typedOver"]["text"] == "Default value: $41.00"


@needs_node
def test_the_labor_rate_formula_reads_only_a_plain_positive_dollar_figure(ran):
    assert ran["laborRate"]["parsed"] == [33.5, 41, None, None, None, None, None]
    assert ran["laborRate"]["fetchedMarkup"] is True


# ── Lodging + Per Diem on the Labor step (Kyle's notes, B7, 2026-10-05) ─────
@needs_node
def test_the_labor_step_draws_a_dividing_line_then_the_three_travel_lines(ran):
    """Hanz: "Line to separate travel; make labor for travel titled Travel Labor; separate line for
    Travel Lodging and Per Diem; note the 70 mile rule." The Labor step draws the tasks, the Add
    button, the Labor total, THEN a dividing line, then Travel Labor, Lodging and Per Diem, each
    with its own 70-mile note. A fresh Lodging card starts OFF (grayed).

    Mutation: render travelRows before the separator, or drop the note from travelCard."""
    t = ran["travelCosts"]
    o = t["order"]
    assert 0 < o["addLine"] < o["sep"] < o["travelLabor"] < o["lodging"] < o["perDiem"], (
        "the Labor step is not tasks, divider, Travel Labor, Lodging, Per Diem: %r" % o)
    assert t["travelLaborLabel"] == "Travel Labor", "a saved draft's Travel row was not relabeled"
    assert t["cardClassOff"], "a fresh Lodging card is not drawn grayed and off"
    assert t["noteOnEach"] >= 3, "the 70-mile note is missing from a travel line: %r" % t["noteOnEach"]


def test_auto_nights_are_the_crew_man_days_exactly_as_pricing_py_counts_them():
    """The beta's auto Lodging/Per Diem quantity (travelQty = travelManDays, NOT divided by crew
    size) must equal the nights backend/pricing.py bills a non-local job. The 2026-10-05 decision
    says "man-days / crew size as pricing.py does"; pricing.py's nights are labor_raw/rate/8, which
    IS the man-days (guys x days), so the two agree and the page follows the engine. Dividing by
    crew size would make the on-screen bid disagree with pricing.py's D68 by the crew-size factor.
    This is real code on both sides: compute_full_bid local vs not-local, crew 3 x (5 + .5 + .5)."""
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from pricing import compute_full_bid
    crews = [(3, 5), (3, 0.5), (3, 0.5)]
    far = compute_full_bid(9000, 10000, crews=crews, local=False)["travel"]
    near = compute_full_bid(9000, 10000, crews=crews, local=True)["travel"]
    man_days = sum(g * d for g, d in crews)  # 18
    assert near == 0
    assert far == man_days * 70 + man_days * 45 == 2070


@needs_node
def test_lodging_and_per_diem_price_inside_the_bid_and_off_adds_nothing(ran):
    """THROUGH THE PAGE'S OWN HANDLERS. Switching Lodging on moves the bid by the nights (the crew's
    16.5 man-days at the saved bid's $70) AND the markups on top -- more than the travel dollars --
    while off adds exactly nothing. The quantity box shows the auto figure, typing leaves auto and
    prices the typed number, and the switch brings it back.

    Mutation: leave `travel:` out of bid() in polish-estimate.js -- the switch moves nothing."""
    t = ran["travelCosts"]
    assert t["baseTravel"] == 0, "a fresh travel line is priced while it is off"
    assert t["lodgingOnTravel"] == 1155 == 16.5 * 70
    assert t["lodgingOnSub"] == t["baseSub"] + 1155, "travel is not in the sub-total"
    assert t["lodgingOnTotal"] - t["baseTotal"] > 1155, (
        "the bid grew by no more than the travel dollars, so the markups are not applied to it")
    assert t["lodgingModel"]["enabled"] is True and t["lodgingModel"]["hand"] is True, (
        "the slider must write an explicit true and mark the line as set by hand")
    assert t["costCellOn"] == "$1,155" and t["qtyAuto"] == "16.5"
    assert t["typedLodging"]["qty_auto"] is False and t["typedTravel"] == 700, (
        "typing a quantity did not leave auto and price on the typed number")
    assert t["typedCostCell"] == "$700", "the cost cell did not repaint live: %r" % t["typedCostCell"]
    assert t["backToAuto"]["qty_auto"] is True and t["backToAuto"]["qty"] == 16.5
    assert t["bothOnTravel"] == 1155 + 990, "per diem at a typed $60 over 16.5 days is $990"
    assert t["perDiemOffTravel"] == 1155, "switching per diem off again did not take it out"


@needs_node
def test_an_off_travel_line_is_left_out_of_review_and_the_saved_draft_says_what_is_on(ran):
    """Review's Hotel and Per Diem card lists only the lines that are ON; an off line is out of the
    list. The saved draft carries the whole travel block, enabled flags and the typed rate
    included, so a reload shows what was priced.

    Mutation: skip the `!tl.enabled` return in reviewPanel -- the off Per Diem reappears."""
    t = ran["travelCosts"]
    assert t["reviewHasCard"] and t["reviewHasLodging"] and t["reviewHasPerDiem"]
    assert t["reviewOffHasLodging"] and not t["reviewOffHasPerDiem"], (
        "an off line is still listed on Review")
    s = t["savedTravel"]
    assert s["lodging"]["enabled"] is True and s["per_diem"]["enabled"] is True
    assert str(s["per_diem"]["rate"]) == "60", "the typed Per Diem rate was not saved"


NOT_INCLUDED = "Not included. Switch Lodging or Per Diem on in the Labor step."


@needs_node
def test_review_always_draws_hotel_and_per_diem_with_a_note_when_both_are_off(ran):
    """Hanz (2026-10-06): the Review step has a container titled Hotel and Per Diem on every bid.
    With both lines off (the default) it is still there, says nothing is included, and is $0 in the
    header and on its total row; the old title is gone.

    Mutation: wrap the card in `if (trvRows.length)` again -- the container vanishes."""
    c = ran["hotelCard"]["off"]
    assert c["count"] == 1, "Review has no Hotel and Per Diem container when both lines are off"
    assert NOT_INCLUDED in c["body"]
    assert c["header"] == "$0" and c["total"] == "$0" and c["travel"] == 0
    assert ">Hotel<" not in c["body"] and ">Per Diem<" not in c["body"], "an off line was listed"
    assert not ran["hotelCard"]["oldTitleAnywhere"], "Review still carries the old card title"


@needs_node
def test_review_hotel_card_lists_only_lines_that_are_on_and_totals_the_bid_travel(ran):
    """One line on: it is listed as Hotel with nights x rate and no note. Both on: both listed, and
    the Hotel and Per Diem Total row and header equal the bid's travel figure to the dollar.

    Mutation: total the card from anything but b.travel -- the total stops matching."""
    one, both = ran["hotelCard"]["one"], ran["hotelCard"]["both"]
    assert ">Hotel<" in one["body"] and ">Per Diem<" not in one["body"]
    assert NOT_INCLUDED not in one["body"]
    assert one["travel"] > 0 and one["total"] == one["header"]
    assert ">Hotel<" in both["body"] and ">Per Diem<" in both["body"]
    assert NOT_INCLUDED not in both["body"]
    assert both["travel"] > one["travel"], "Per Diem added nothing to the card"
    expected = "${:,.0f}".format(both["travel"]) if both["travel"] == int(both["travel"]) \
        else "${:,.2f}".format(both["travel"])
    assert both["total"] == expected == both["header"]


@needs_node
def test_a_renamed_lodging_label_is_shown_instead_of_hotel(ran):
    """The estimator's own label on the lodging line wins; only the untouched default reads Hotel.

    Mutation: force "Hotel" for every label -- the saved Motel line is relabelled."""
    body = ran["hotelCard"]["renamed"]["body"]
    assert ">Motel<" in body and ">Hotel<" not in body


@needs_node
def test_hotel_card_sits_between_labor_and_the_markup_subtotal(ran):
    """Order on Review: Labor card, then Hotel and Per Diem, then the Subtotal / Markup block.

    Mutation: draw the card before Labor or after the markup table -- the order assertion fails."""
    for k in ("off", "one", "both"):
        c = ran["hotelCard"][k]
        assert 0 < c["labor"] < c["card"] < c["subtotal"], k


@needs_node
def test_a_new_bid_copies_the_two_rates_and_a_saved_bid_keeps_its_own(ran):
    """A NEW bid copies Markups -> Global lodging / per diem ($80 / $50 in the fixture) and both
    start OFF; a read that fails leaves the shipped $70 / $45; a saved bid keeps the 70 it was
    stored with even though the company rate is now 80.

    Mutation: apply the rates outside the `if (laborDefaults)` gate -- the saved bid becomes 80."""
    t = ran["travelCosts"]
    assert t["freshRates"] == {"lodging": 80, "per_diem": 50}
    assert t["freshEnabled"] == [False, False]
    assert t["downRates"] == {"lodging": 70, "per_diem": 45}
    assert t["oldRates"]["lodging"] == 70, "a saved bid's lodging rate moved to the new company rate"


@needs_node
def test_a_local_job_grays_all_three_until_one_is_touched(ran):
    """Under 70 miles (the `local` answer) the cards are gray; switching one on is the estimator's
    choice, lifts the dim on that card and marks it by hand so the distance rule cannot undo it.

    Mutation: drop `hand` from travelInert -- the card stays gray after being switched on."""
    t = ran["travelCosts"]
    assert "inert" in t["localClass0"]
    assert "inert" not in t["localClassOn"] and t["localHand"] is True


# ── DISTANCE DECIDES "LOCAL" (Kyle 9/18; Hanz, 2026-10-05) ──────────────────────────────────────
# Executed through the page: init() asks POST /api/distance after the first paint, and the answer
# sets the hidden conditions.local (still written to Polish!B4), the three travel lines and the
# "N mi from Olathe office" note.

UNKNOWN_NOTE = "Distance unknown — enter miles"


def test_a_far_job_turns_the_three_travel_lines_on_and_writes_no_to_b4(ran):
    """120.4 driving miles: not local, Lodging and Per Diem on, Travel Labor un-grayed, the note says
    so, Review lists Lodging, and Polish!B4 is written "No" from the hidden answer.

    Mutation: leave `conditions.local` alone in B.applyDistance, or stop writing the cell."""
    d = ran["distance"]
    assert d["requestBody"] == {"address": "100 Main St", "city": "Wichita", "state": "KS",
                                "zip": "67202"}
    assert d["requests"] == 1
    f = d["far"]
    assert f["note"] == "120.4 mi from Olathe office"
    assert f["local"] is False and f["lodging"] is True and f["perDiem"] is True
    assert f["lodgingGray"] is False and f["travelLaborGray"] is False
    assert d["farCellB4"] == "No" and d["farModelLocal"] is False
    assert d["farSavedDistance"]["miles"] == 120.4, "the figure is cached on the draft"
    assert d["farReviewHasLodging"] is True


def test_a_near_job_is_local_and_all_three_travel_lines_stay_gray(ran):
    d = ran["distance"]
    n = d["near"]
    assert n["note"] == "30 mi from Olathe office"
    assert n["local"] is True and n["lodging"] is False and n["perDiem"] is False
    assert n["lodgingGray"] is True and n["travelLaborGray"] is True
    assert d["nearCellB4"] == "Yes"
    # Exactly 70 is far: "70 miles or more".
    assert d["seventy"] == {"local": False, "lodging": True}


def test_unknown_distance_never_guesses_and_the_estimator_can_type_miles(ran):
    """No key / address not found / the service down: the line says so, the bid is unchanged (local,
    all three gray), and a typed figure takes over -- and wins over everything after it.

    Mutation: default an unknown distance to far (or to a number), or drop the typed override."""
    d = ran["distance"]
    u = d["unk"]
    assert u["note"] == UNKNOWN_NOTE and u["distance"] is None
    assert u["local"] is True and u["lodging"] is False and u["lodgingGray"] is True
    assert "not set up" in u["status"]
    t = d["typed85"]
    assert t["distance"]["source"] == "typed" and t["distance"]["miles"] == 85
    assert t["local"] is False and t["lodging"] is True and t["perDiem"] is True
    assert t["note"] == "85 mi from Olathe office (typed by you)"
    # The network going away is the same answer, with its own words.
    dn = d["down"]
    assert dn["note"] == UNKNOWN_NOTE and dn["local"] is True and dn["lodging"] is False
    assert "did not answer" in dn["status"]


def test_a_line_flipped_by_hand_is_never_moved_by_the_distance(ran):
    """Lodging was flipped off by hand at 85 miles. Typing 20 and then 90 moves Per Diem (never
    touched) both ways and leaves Lodging off both times. Clearing the miles returns to unknown.

    Mutation: ignore `hand` in B.applyDistance."""
    d = ran["distance"]
    assert d["typed20"]["lodgingHand"] is True
    assert (d["typed20"]["lodging"], d["typed20"]["perDiem"], d["typed20"]["local"]) == (False, False, True)
    assert (d["typed90"]["lodging"], d["typed90"]["perDiem"], d["typed90"]["local"]) == (False, True, False)
    c = d["cleared"]
    assert c["distance"] is None and c["note"] == UNKNOWN_NOTE
    assert c["local"] is True and c["perDiem"] is False and c["lodging"] is False


def test_a_typed_decimal_in_the_miles_box_survives_the_rebuild(ran):
    """The panel rebuilds on each keystroke; "12." must stay "12." so "12.5" is 12.5 miles (local),
    not 125 (far, with Lodging and Per Diem switched on)."""
    dec = ran["distance"]["decimal"]
    assert dec["dotBox"] == "12."
    assert dec["box"] == "12.5"
    assert dec["snap"]["distance"]["miles"] == 12.5
    assert dec["snap"]["local"] is True and dec["snap"]["lodging"] is False


def test_a_slow_google_never_blocks_the_page_and_typed_miles_win(ran):
    """init() resolved while the answer was still pending (the Labor step rendered, "Looking up"
    shown); the estimator typed 10 meanwhile; when 200 miles finally arrived it was dropped.

    Mutation: await the lookup inside init(), or apply the late answer over a typed one."""
    d = ran["distance"]
    assert "Looking up" in d["slowBusy"]["status"] and d["slowBusy"]["distance"] is None
    a = d["slowAfter"]
    assert a["distance"]["source"] == "typed" and a["distance"]["miles"] == 10
    assert a["local"] is True and a["lodging"] is False


def test_no_usable_address_means_no_request_and_a_plain_message(ran):
    d = ran["distance"]
    assert d["blankRequests"] == 0 and d["thinRequests"] == 0
    assert d["blank"]["note"] == UNKNOWN_NOTE
    assert "intake step" in d["blank"]["status"]


def test_a_saved_bid_is_not_repriced_until_the_estimator_asks(ran):
    """A bid with stated labor never looks the distance up on its own (that would add lodging to a
    bid already quoted); the button does it, and the answer applies.

    Mutation: drop the new-bid gate in init()."""
    d = ran["distance"]
    assert d["savedFetches"] == 0
    assert d["savedBefore"]["note"] == UNKNOWN_NOTE and d["savedBefore"]["lodging"] is False
    s = d["savedAfter"]
    assert s["note"] == "150 mi from Olathe office" and s["lodging"] is True and s["local"] is False


# ── "HOW THIS IS WORKED OUT" under the Travel heading (Hanz, 2026-10-06) ─────────────────────────
# Executed through the page: the note is read out of the real DOM after the real init()/typing, and
# the dollar figures in it are held to B.travelLineCost / B.laborCost (what the bid itself prices).

def _how_line(how, label):
    """The one line of the note that starts with `label` (a travel line's name)."""
    for line in how.split("\n"):
        if line.startswith(label + ":"):
            return line
    raise AssertionError("no %r line in the note: %r" % (label, how))


def _last_dollars(line):
    """The last dollar figure on a line, as a number: the line's answer."""
    import re
    return float(re.findall(r"\$([\d,]+(?:\.\d+)?)", line)[-1].replace(",", ""))


def test_the_how_note_on_a_far_job_says_not_local_and_shows_every_sum(ran):
    """150 miles: the note says NOT local, shows the three sums with real numbers, and each sum's
    answer is exactly what the bid prices that line at.

    Mutation: drop the note from laborPanel, or compute the sums in the note a second way."""
    f = ran["distance"]["howNights"]["auto"]
    how = f["how"]
    assert how.startswith("150 mi from Olathe office. That is 70 miles or more, so this is NOT a "
                          "local job: Travel Labor, Lodging and Per Diem come on.")
    for label, key in (("Lodging", "lodging"), ("Per Diem", "per_diem")):
        line = _how_line(how, label)
        assert _last_dollars(line) == f["cost"][key] > 0
        assert " x $" in line
    assert "nights x $70.00" in _how_line(how, "Lodging")
    assert "days x $45.00" in _how_line(how, "Per Diem")
    travel = _how_line(how, "Travel Labor")
    assert "drive hours (round trip at 60 mph)" in travel
    assert _last_dollars(travel) == f["cost"]["travel"] > 0
    assert "Man-days = guys x days on the labor lines above" in how


def test_the_how_note_on_a_local_job_says_so_and_shows_the_lines_off(ran):
    """30 miles: IS a local job, and all three lines read off, $0.

    Mutation: say far for a near job, or show sums for a gray line."""
    how = ran["distance"]["near"]["how"]
    assert how.startswith("30 mi from Olathe office. That is under 70 miles, so this IS a local "
                          "job: the three travel lines stay gray unless you switch one on.")
    for label in ("Travel Labor", "Lodging", "Per Diem"):
        assert _how_line(how, label) == label + ": off, $0"


def test_the_how_note_when_the_distance_is_unknown_asks_for_the_miles(ran):
    """No distance: it does not pretend to know, and tells the estimator what to type.

    Mutation: treat unknown as local or as far."""
    how = ran["distance"]["unk"]["how"]
    assert how.startswith("Distance not known yet, so the tool cannot tell if this is a local job. "
                          "Type the miles above.")
    assert _how_line(how, "Lodging") == "Lodging: off, $0"


def test_the_how_note_names_a_line_the_estimator_switched_by_hand(ran):
    """Lodging was flipped off by hand at 85 miles; at 90 the distance would turn it on but does not,
    and the note says exactly that, while Per Diem (never touched) is on.

    Mutation: drop the `hand` sentence, or show Lodging's sum for a line that is off."""
    d = ran["distance"]["typed90"]
    assert "Lodging was switched off by hand, so the distance does not change it." in d["how"]
    assert _how_line(d["how"], "Lodging") == "Lodging: off, $0"
    assert _last_dollars(_how_line(d["how"], "Per Diem")) == d["cost"]["per_diem"] > 0
    assert "Per Diem was switched" not in d["how"]


def test_the_how_note_says_typed_when_nights_were_typed_and_repaints_with_the_miles(ran):
    """Typing 10 nights marks the line (typed) and the note's figure follows; typing 20 miles over the
    150 repaints the note in place to a local job, with no rebuild of the page's other cards.

    Mutation: leave the note out of paintDistance (it would still read 'NOT a local job'). The
    repaintNumbers path is held by the typed-labor-day test below."""
    h = ran["distance"]["howNights"]
    assert "(typed)" not in _how_line(h["auto"]["how"], "Lodging")
    typed = _how_line(h["typed"]["how"], "Lodging")
    assert "10 nights (typed) x $70.00 = $700.00" in typed
    assert _last_dollars(typed) == h["typed"]["cost"]["lodging"] == 700
    moved = h["local"]["how"]
    assert moved.startswith("20 mi from Olathe office (typed by you). That is under 70 miles, so "
                            "this IS a local job")
    assert "NOT a local job" not in moved


def test_the_how_note_follows_a_typed_labor_day_without_a_rebuild(ran):
    """Typing Days on a labor line takes changed(false), which repaints in place and never rebuilds the
    panel, so the note's man-days and dollars move only if repaintNumbers paints the note. The figure in
    the note must equal what the bid prices the line at, before and after.

    Mutation: drop the data-trv-how line from repaintNumbers (the note keeps the old man-days)."""
    h = ran["distance"]["howDays"]
    before, after = h["before"], h["after"]
    assert _last_dollars(_how_line(before["how"], "Lodging")) == before["cost"]["lodging"] > 0
    assert after["cost"]["lodging"] != before["cost"]["lodging"]
    assert _last_dollars(_how_line(after["how"], "Lodging")) == after["cost"]["lodging"]
    assert _last_dollars(_how_line(after["how"], "Per Diem")) == after["cost"]["per_diem"]
    assert after["how"] != before["how"]


# ── B7b: the Labor Calculator fills a NEW bid's default labor lines ──────────────────────────────
def test_a_new_bid_fills_its_default_labor_from_the_calculator(ran):
    """From SF: crew 3, 2,500 SF/day, 12,000 SF job -> 5 days at 10 h, company rate $40 = $6,000.
    Fixed: 2 guys x 1 day at its own $50. A line with no mode keeps today's blank row.
    Mutation: apply before the takeoff is seeded (days blank), or skip the laborCalc gate."""
    lc = ran["laborCalc"]
    p = lc["first"]["polishing"]
    assert (p["guys"], p["days"], p["rate"], p["hours_per_day"]) == (3, 5, 40, 10)
    assert lc["first"]["cost"] == 6000
    m = lc["first"]["mockup"]
    assert (m["guys"], m["days"], m["rate"]) == (2, 1, 50)
    j = lc["first"]["jointfill"]
    # A line with no saved mode still opens as the shipped crew line did (3 guys, blank days, the
    # company rate): the shipped starting crew stands in for a calculator row (Phase LS1).
    assert j["days"] == "" and j["guys"] == 3 and j["rate"] == 40
    assert j["calc_default"]["guys"] == 3 and j["calc_default"]["rate"] == 40


def test_changing_a_calculator_figure_shows_the_default_value_warning_and_typing_it_back_clears_it(ran):
    lc = ran["laborCalc"]
    assert lc["first"]["warnDays"] == {"text": "", "hidden": True}
    assert lc["first"]["warnRate"] is True
    assert lc["over"] == {"text": "Default value: 5", "hidden": False}
    assert lc["back"] == {"text": "", "hidden": True}
    assert lc["hrs"] == {"warn": {"text": "Default value: 10 hours", "hidden": False}, "cost": 4800}
    # a rate typed over the calculator's OWN rate warns against that rate, not the company's
    assert lc["mockRateBefore"] is True and lc["mockRateAfter"] == "Default value: $50.00"
    assert lc["first"]["hoursSelect"] is True


def test_a_saved_bid_is_never_recomputed_and_does_not_even_ask(ran):
    sv = ran["laborCalc"]["saved"]
    assert (sv["polishing"]["guys"], sv["polishing"]["days"]) == (4, 6) and sv["asked"] is False


def test_no_sf_leaves_days_blank_and_an_absent_table_opens_exactly_as_before(ran):
    lc = ran["laborCalc"]
    assert lc["noSf"]["days"] == "" and lc["noSf"]["guys"] == 3
    # typing days over a blank default must not warn "Default value: blank"
    w = lc["noSfWarn"]
    assert w is not None and (w["hidden"] or w["text"].strip() == "")
    # An absent calculator table opens the crew lines exactly as before: the shipped starting crew
    # (3 guys, blank days) is what fills them, so the figures are the same ones.
    assert lc["gone"]["same"] is True
    assert lc["gone"]["polishing"]["guys"] == 3 and lc["gone"]["polishing"]["days"] == ""


def test_labor_days_follow_the_takeoff_until_the_estimator_edits_them(ran):
    """G2. A From-SF line (3 crew, 2,500 SF/day): 12,000 SF -> 5 days; the takeoff goes to 20,000 ->
    8 days, in the box too, with no 'Default value' warning; a fixed line never moves. After the
    estimator types 11 the next SF change leaves 11. A new bid with no SF fills days as soon as SF
    exists (5,000 -> 2). A SAVED bid's stale marker row (9 days on 17,500 SF) is not recomputed on
    open or by an unrelated edit.

    Mutation: drop the followLaborDays call in changed() -- afterUp stays 5."""
    f = ran["laborCalc"]["followed"]
    assert f["start"] == 5
    assert f["afterUp"] == 8 and f["boxAfterUp"] == "8"
    assert f["warnAfterUp"] == {"text": "", "hidden": True}
    assert f["fixedStays"] == 1
    assert str(f["editedStays"]) == "11"
    assert f["noSfBlank"] == "" and f["noSfFilled"] == 2
    assert f["savedOnOpen"] == 9 and f["savedAfterOtherEdit"] == 9
    assert f["pureMoves"] == [4, 5]


def test_lodging_and_per_diem_rates_warn_against_the_markup_global_rate_they_were_filled_with(ran):
    """G3. New bid, Markups -> Global lodging $80 / per diem $50: both open at those and neither
    warns. Typing 90 over lodging warns 'Default value: $80.00'; typing 80 back clears it. A saved
    bid (no stamp) shows nothing.

    Mutation: drop the rate_default stamp in applyTravelRates -- the warning never shows."""
    w = ran["laborCalc"]["travelWarn"]
    assert w["rates"] == [80, 50]
    assert all(x["hidden"] for x in w["start"]), w["start"]
    assert w["over"] == {"text": "Default value: $80.00", "hidden": False}
    assert w["back"]["hidden"] is True
    assert all(x["hidden"] for x in w["saved"]), w["saved"]


def test_the_beta_page_writes_no_labor_cells_so_the_hours_per_day_cannot_split_the_workbook(ran):
    """G4. Kyle's Polish tab prices labor as D37 = (A37*B37*C37)*IF($E$35="8 hour days",8,10) with ONE
    sheet-wide E35, so a workbook labor cell holding a 10-hour line's days would be priced at 8.
    What THIS page actually writes on a save (a bid mixing 10- and 8-hour lines): only the condition
    cells and the Dye / Joint Filler rate and quantity cells -- never rows 35-46 of Polish (labor,
    travel, E35) nor any Epoxy labor row. So the screen's labor ($6,000 + $640 = $6,640 here) never
    reaches the workbook at all and the mixed-hours split cannot occur.

    This pins that. The day a writer is added for those cells it MUST scale each line's days by
    its hours_per_day / 8 (E35 stays '8 hour days'), and this test goes red to say so.

    Mutation: have saveSoon add any Polish!A37..D46 key to cell_values -- this fails."""
    import re
    w = ran["laborWrites"]
    assert w["screenLabor"] == 3 * 5 * 40 * 10 + 2 * 1 * 40 * 8
    labor_rows = re.compile(r"^Polish!([A-Z]+)(3[5-9]|4[0-6])$")
    hit = [k for k in w["keys"] if labor_rows.match(k) or k.startswith("Epoxy!") and
           re.match(r"^Epoxy!([A-Z]+)(4[5-9]|5[0-9])$", k)]
    assert hit == [], "the page now writes labor cells -- scale days by hours_per_day/8: %r" % hit


def test_a_new_bids_fees_line_starts_at_the_defaults_tab_amount(ran):
    """EXECUTED THROUGH THE PAGE'S OWN init (Hanz, 2026-10-06). A NEW bid's Fees + Textura starts at
    the Global `fees_textura` rule, priced into the lump sum; typing over it shows the shared amber
    "Default value: $N" and typing the default back clears it; the default rides the saved model so
    the warning survives a reload; a SAVED bid keeps its own fees and shows no warning; no default
    or a $0 one leaves the line at $0 with no warning.

    Mutation: drop B.applyFeesDefault from init() and startModel/startTotal go red; drop
    fees_default from migrateModel and reloadWarn goes red; apply it to a saved bid and
    savedBidFees goes red."""
    f = ran["feesDefault"]
    assert f["startModel"] == {"fees": 250, "fees_default": 250}
    assert f["startBox"] == "250" and f["startWarn"]["hidden"] is True
    assert f["startTotal"] > f["noneTotal"], "the default did not reach the lump sum"
    assert f["overWarn"] == {"text": "Default value: $250.00", "hidden": False}
    assert f["overTotal"] > f["startTotal"]
    assert f["backWarn"]["hidden"] is True
    assert f["savedHasDefault"] == 250
    assert f["reloadWarn"] == {"text": "Default value: $250.00", "hidden": False}
    assert f["noneFees"] == 0 and f["noneDefault"] and f["noneBox"] == "0"
    assert f["noneWarn"]["hidden"] is True
    assert f["zeroDefault"] and f["zeroWarn"]["hidden"] is True and f["zeroFees"] == "75"
    assert f["savedBidFees"] == 75 and f["savedBidDefault"] and f["savedBidWarn"]["hidden"] is True


def test_the_fees_default_reads_only_a_plain_filed_applying_global_number(ran):
    r = ran["feesDefault"]["rules"]
    assert r["plain"] == 250 and r["dollar"] == 1250 and r["decimal"] == 99.5
    assert r["zero"] == 0, "zero is a real answer, not nothing"
    for k in ("off", "expr", "blank", "none", "notList", "otherLine", "otherLayout"):
        assert r[k] is None, k


# ── every default-pulled row's estimate toggle moves the lump sum (Hanz, 2026-10-06) ──────────────
_PULLED_ROWS = [
    "default assembly takeoff row", "default material takeoff row", "joint filler condition row",
    "dye condition row", "favorited custom labor line", "Travel Labor", "Lodging", "Per Diem",
]


def test_the_new_bid_really_pulled_in_one_of_every_default(ran):
    base = ran["toggleMovesTotalBase"]
    assert base["takeoff"] == ["a1", "i4"], base
    assert base["labor"] == ["polishing", "mockup", "jointfill", "travel", "c1"], base
    assert base["total"] > 0


@pytest.mark.parametrize("name", _PULLED_ROWS)
def test_a_default_rows_switch_moves_the_lump_sum_by_exactly_its_contribution(ran, name):
    """EXECUTED THROUGH THE PAGE: a library with non-zero prices, a NEW bid, a click on the row's
    own switch. The total after the click equals an oracle priced by the two real engines from the
    model with that one flag changed; clicking again returns the original total to the dollar.
    A row that started OFF (conditions, Lodging, Per Diem) rises; one that started ON drops.

    Mutation: make laborCost ignore rowOn, make materialTotal skip the rowOn test, drop the
    `if (M.conditions.dye)` gate, or have travelLineCost ignore rowOn -- the matching row goes red."""
    r = ran["toggleMovesTotal"][name]
    assert r["hasSwitch"], "%s has no switch on the estimate" % name
    assert r["afterFlip"] != r["before"], "%s: the toggle did not move the lump sum" % name
    assert r["afterFlip"] == r["oracleFlip"], (
        "%s: the lump sum after the click is not what the engines price for that change" % name)
    assert r["back"] == r["before"], "%s: switching back did not restore the total" % name
    if r["startOn"]:
        assert r["afterFlip"] < r["before"], "%s: switching an included row off did not drop it" % name
    else:
        assert r["afterFlip"] > r["before"], "%s: switching an excluded row on did not raise it" % name


@pytest.mark.parametrize("name,gray", [
    ("default assembly takeoff row", "inert"), ("default material takeoff row", "inert"),
    ("favorited custom labor line", " off"), ("Travel Labor", " off"),
    ("Lodging", " off"), ("Per Diem", " off")])
def test_an_off_default_row_is_grayed_and_an_on_one_is_not(ran, name, gray):
    r = ran["toggleMovesTotal"][name]
    off_card = r["cardAfterFlip"] if r["startOn"] else r["cardBefore"]
    on_card = r["cardBefore"] if r["startOn"] else r["cardAfterFlip"]
    assert gray in off_card, "%s: switched off but not grayed: %r" % (name, off_card)
    assert gray not in on_card, "%s: switched on but still grayed: %r" % (name, on_card)
    sw_off = r["swAfter"] if r["startOn"] else r["swBefore"]
    assert sw_off == "false"


def test_the_remove_existing_switch_moves_the_lump_sum(ran):
    r = ran["toggleMovesTotal"]["remove-existing condition row"]
    assert r["hasSwitch"] and r["swAfter"] == "true"
    assert r["afterFlip"] != r["before"]


# ── the two toggles are independent (Hanz, 2026-10-06) ────────────────────────────────────────────
def test_a_library_default_on_only_sets_a_new_bids_starting_state(ran):
    """(3) EXECUTED THROUGH init: the same library with default_on true / false / never set. True and
    unset open every default row ON; false opens the default assembly, material, custom labor line and
    Travel Labor OFF, and the lump sum is lower by their contributions.

    Mutation: make seedDefaultTakeoff ignore default_on, or seedLibraryLabor ignore it."""
    t = ran["toggleIndependence"]
    assert t["startsOn"]["takeoff"] == [True, True] and t["startsUnset"] == t["startsOn"]
    assert "travel:true" in t["startsOn"]["labor"] and "c1:true" in t["startsOn"]["labor"]
    off = t["startsOff"]
    assert off["takeoff"][:2] == [False, False]
    assert "travel:false" in off["labor"] and "c1:false" in off["labor"]
    assert off["total"] < t["startsOn"]["total"]


def test_flipping_rows_on_an_estimate_never_writes_to_the_library(ran):
    """(1) Every takeoff row, every labor row, Lodging and Dye switched on the estimate, the bid
    saved: not one request left the page after init (so no PATCH/POST/PUT/DELETE of /api/library*),
    and the library fixture the page read is byte-identical afterwards. The flips did change the bid.

    Mutation: have the on/off handlers call api('/api/library/...', {method:'PATCH'})."""
    t = ran["toggleIndependence"]
    assert t["flipCalls"] == [], t["flipCalls"]
    assert t["libraryUntouched"] is True
    assert t["flippedDiffers"] is True


def test_changing_a_library_default_on_after_a_bid_is_saved_changes_nothing_on_that_bid(ran):
    """(2) A bid saved with the default assembly row and the custom labor line switched OFF, reopened
    under the same library, under one whose default_on is false everywhere (so the rows it left ON --
    material, Travel -- are told OFF by the library) and under one whose default_on now agrees with
    the flips: identical row states and the identical total each time.

    Mutation: let the new-bid seeding run on a bid that already has a saved model."""
    t = ran["toggleIndependence"]
    assert t["savedFlips"] == {"takeoff0": False, "c1": False}
    s = t["saved"]
    assert s["here"]["takeoff"] == [False, True]
    assert "travel:true" in s["here"]["labor"] and "c1:false" in s["here"]["labor"]
    assert s["libOff"] == s["here"], "a library default_on change reached a saved bid"
    assert s["libMatches"] == s["here"], "a library default_on change reached a saved bid"


def test_the_takeoff_cards_are_the_tables_rows_joined_with_this_pages_views(ran):
    """PHASE 7. Which cards there are, in what order, and each one's workbook cell, reserved library row
    and dependency come out of the one conditions table (js/work-types.js: the conditions the Takeoff step
    asks of a polish job). What a card SAYS is this page's own (CARD_VIEWS). The harness reads the page's real
    CONDITION_CARDS after the real parse, so a card typed back into the page with its own cell, or a table
    row with no view, shows up here.

    Remove-existing is the card that does not price: it is a fourth hand on the joint-filler line, and it is
    the only one that `needs` another. Each priced card's hint still names its cell in words, which is text
    this page types, so that is checked against the cell the table gave it.

    Mutation: change a cell or an item_id in the CARD_VIEWS joined row, or add a v2Takeoff row to the table
    with no view."""
    cards = ran["cards"]
    assert cards["rows"] == [
        {"key": "joint_filler", "cell": "Polish!E29", "item_id": "joint-filler-kit", "needs": None,
         "prices": True, "hintNamesItsCell": True},
        {"key": "remove_existing_jf", "cell": "Polish!F29", "item_id": "remove-existing-jf",
         "needs": "joint_filler", "prices": False, "hintNamesItsCell": None},
        {"key": "dye", "cell": "Polish!E25", "item_id": "dye", "needs": None,
         "prices": True, "hintNamesItsCell": True},
    ]
    assert cards["reserved"] == ["joint-filler-kit", "remove-existing-jf", "dye"], (
        "the ids kept out of every takeoff-row picker are the ids of the cards, in the cards' order")


# ── one search pop-up adds Takeoff rows and Labor cards (Hanz, 2026-10-09) ────────────────────────
# Run by section N of the harness: the REAL library-picker.js mounted on the harness's DOM, opened
# by the page's own Add buttons. Mutation proofs are named per test.

@needs_node
def test_the_takeoff_button_opens_a_pop_up_and_adds_nothing_by_itself(ran):
    """Mutation: put `M.takeoff.push({kind: "new", ...})` back in the [data-add-row] handler. `after`
    becomes 4 and an empty row sits on the takeoff before anything was picked."""
    o = ran["addPopup"]["takeoffOpen"]
    assert o["popupOn"] and o["after"] == o["before"], "the click added a row, or no pop-up opened"
    assert o["addDisabled"], "Add is live with nothing ticked"
    # assemblies AND materials, the same set the row's own field offers, minus a reserved material
    keys = o["keys"]
    assert {"asm:a1", "asm:a2", "item:i1", "item:i4"} <= set(keys)
    assert not o["reservedListed"], "a reserved material (dye, joint filler) is offered as a takeoff row"
    n = ran["addPopup"]["noPick"]
    assert n["rows"] == o["before"] and n["stillOpen"] and n["addDisabled"]
    assert n["enterPrevented"], "Enter in the search box was left to do whatever it does"


@needs_node
def test_the_search_narrows_and_a_tick_survives_it_and_esc_closes_and_returns_focus(ran):
    p = ran["addPopup"]
    assert p["searched"]["keys"] == ["asm:a2"]
    assert p["searchedNone"]["keys"] == [] and not p["searchedNone"]["noneHidden"]
    assert p["searchedNone"]["count"] == "1 picked", "a pick was lost when the search hid its row"
    assert p["esc"]["closed"] and p["esc"]["rows"] == 3 and p["esc"]["focusedBack"] == 1, (
        "Esc did not close the pop-up, or the focus did not return to the button: %r" % p["esc"])
    assert p["cancel"]["closed"] and p["cancel"]["rows"] == 3 and p["cancel"]["focusedBack"] == 2


@needs_node
def test_ticked_lines_become_rows_resolved_the_way_the_rows_own_field_resolves_them(ran):
    """Mutation: skip becomeKind/setAssembly/setMaterial and write the ids by hand. The row loses
    the assembly's own unit (Cove Base is LF) or the material's coverage key, and stops matching the
    row typing its name produces."""
    p = ran["addPopup"]
    assert p["ticked"]["count"] == "4 picked" and not p["ticked"]["addDisabled"]
    assert p["untickedCount"] == "3 picked", "unticking did not take the pick back off"
    a = p["added"]
    assert a["before"] == 3 and a["after"] == 6 and a["closed"], a
    cove, densifier, grout = a["rows"]
    assert cove == p["typed"]["a2"], "popup row differs from the typed one: %r vs %r" % (cove, p["typed"]["a2"])
    assert densifier == p["typed"]["i4"]
    # The two things named "Grout Compound": the ticked one is the one that lands, never a guess.
    assert grout["kind"] == "asm" and grout["assembly_id"] == "a6"
    assert a["focusedBack"] == 3 and p["pickedCost"]["cell"] == "$1,100"
    assert p["pickedCost"]["expected"] == 1100
    # A lone untouched starting row is replaced by the first pick, not left beneath it.
    assert p["lone"] == {"before": 1, "after": ["a1"]}


@needs_node
def test_esc_closes_the_pop_up_even_when_focus_is_outside_it(ran):
    """Mutation: remove the document keydown listener in library-picker.js. Esc fired on body (focus
    after a click on the heading or a locked row) then leaves the pop-up open."""
    o = ran["addPopup"]["escOutside"]
    assert o["closed"] and o["rows"] == 3, o
    assert o["focusedBack"] == 2, "focus did not return to the opener: %r" % o
    assert o["listenersAfter"] == o["listenersWhileOpen"] - 1, (
        "the document listener outlived the pop-up: %r" % o)


@needs_node
def test_a_ticked_assembly_takes_its_own_unit_when_another_shares_its_name(ran):
    """Mutation: drop the unit lines after `row.assembly_id = p.id` in addPickedTakeoffRow. The
    second Cove Base (SF) then lands as LF, the unit of the first one found by name."""
    assert ran["addPopup"]["dupName"] == [{"id": "a2", "unit": "LF"}, {"id": "a2b", "unit": "SF"}]


@needs_node
def test_the_labor_button_lists_the_labor_list_work_type_first_and_never_travel(ran):
    """Mutation: drop the work-type split in shown() (or `first:` in laborPickEntries). The epoxy-only
    line then sorts ahead of the polish ones. Mutation: drop the travel skip and `lab:travel` appears."""
    o = ran["addPopup"]["laborOpen"]
    assert o["popupOn"] and o["after"] == o["before"], "the click added a card"
    keys = o["keys"]
    assert "lab:travel" not in keys
    assert keys.index("lab:L1") < keys.index("lab:L2") and keys.index("lab:L3") < keys.index("lab:L2"), (
        "a line for another work type is listed ahead of this bid's: %r" % keys)
    assert o["addDisabled"] and o["oneOffDisabled"]
    p = ran["addPopup"]
    assert p["laborEmptyOneOff"] == {"rows": 3, "stillOpen": True}, "an empty one-off name added a card"
    assert p["laborNoPick"] == {"rows": 3, "stillOpen": True}
    assert p["laborEsc"] == {"closed": True, "rows": 3, "focusedBack": 1}


@needs_node
def test_a_ticked_labor_line_becomes_the_card_seeding_would_have_made(ran):
    """Mutation: build the card by hand (rate: row.rate). The blank-rate line "Any work" then has
    rate null instead of the company rate, rate_default is missing, and `cards` stops equalling
    `viaSeed`."""
    p = ran["addPopup"]["laborPicked"]
    assert p["cards"] == p["viaSeed"], (p["cards"], p["viaSeed"])
    assert [c["rate_default"] for c in p["cards"]] == [40, 33]
    assert p["closed"] and p["focusedBack"] == 2
    c = ran["addPopup"]["laborCard"]
    assert c["label"] == "Any work v2", "the Task name is not editable"
    assert c["costBlankRate"] == "$198" and c["costBlankRate"] == "$%d" % c["expectedBlankRate"], (
        "a cleared rate no longer falls back to the stamped default: %r" % c)
    assert c["warn"] == {"text": "Default value: $33.00", "hidden": False}
    lk = ran["addPopup"]["laborLocked"]
    assert lk["addedAnother"] == 0 and lk["stillOpen"] and lk["lockedRowMarked"], (
        "a library line already on the bid can be added a second time: %r" % lk)


@needs_node
def test_the_one_off_line_needs_a_name_and_comes_at_the_company_rate(ran):
    """Mutation: let addOneOff skip the name check. The empty Enter in the earlier test then adds a
    nameless card (laborEmptyOneOff.rows becomes 4)."""
    p = ran["addPopup"]
    assert p["oneOffEnabled"]
    o = p["oneOff"]
    assert o["added"] == 1 and o["closed"]
    assert o["card"]["label"] == "Hand grind", "the typed name was not tidied: %r" % o["card"]["label"]
    assert o["card"]["rate"] == 33 and o["card"]["rate_default"] == 33
    assert p["allNamed"], "a nameless Task card exists after using the pop-up"


@needs_node
def test_when_the_labor_list_cannot_be_read_the_shipped_crew_stands_in(ran):
    assert ran["addPopup"]["laborFallback"]["keys"] == ["lab:polishing", "lab:mockup", "lab:jointfill"]


def test_the_old_empty_row_paths_are_gone():
    """The two buttons used to push an empty row (and the delete guards refilled one). Source reads
    are enough for the ABSENCE of the old calls; the behaviour is executed above."""
    src = (FRONTEND / "js" / "polish-estimate.js").read_text(encoding="utf-8")
    assert "newTakeoffRow" not in src, "the empty-takeoff-row constructor is back"
    assert "M.labor.push(newLaborRow())" not in src, "an unnamed Task card can be pushed again"
    assert not re.search(r"newLaborRow\(\s*\)", src), "newLaborRow() is called with no name"
    assert "openTakeoffPicker(addRow)" in src and "openLaborPicker(addLab)" in src
