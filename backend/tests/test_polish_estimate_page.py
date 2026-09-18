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
    is offered, because otherwise there is none short of knowing to clear the field."""
    t = ran["travelGuys"]
    assert t["seeded"] == 16.5, "3x5 + 3x0.5 man-days: %r" % t["seeded"]
    assert t["afterCrewEdit"] == 13.5, (
        "the derived figure did not follow a task above it: %r" % t["afterCrewEdit"])
    assert t["boxShowsIt"] not in ("", "None"), (
        "the box sits empty next to a row that is being priced off the figure")
    assert t["manualLinkOffered"], "no way across to typing one's own figure"
    assert t["afterTyping"] == {"guys": "7", "auto": False}, (
        "typing in the box did not take it off auto: %r" % t["afterTyping"])
    assert t["stickyAfterCrewMoves"] == "7", (
        "a hand-typed figure was overwritten when a task above it changed: %r"
        % t["stickyAfterCrewMoves"])
    assert t["afterBackToAuto"] == {"guys": 28.5, "auto": True}, (
        "back-to-auto did not resume following the tasks above: %r" % t["afterBackToAuto"])


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
def test_the_type_my_own_control_is_a_switch_in_the_card_header(ran, html):
    """Moved out of the small-print hint under Guys and into the card header, and it is now a
    SWITCH rather than a button whose words flip.

    The old control read "Type my own", and once pressed, "Back to auto". That labels the
    ACTION, so at any moment it names the state you are LEAVING rather than the one you are
    in — an estimator glancing at a card could not tell from the words whether Guys was
    derived or typed. A switch says the state and shows it, in one sentence that stays true
    in both positions, and it matches the switches the Review step already uses."""
    lab = ran["labor"]
    assert lab["toggleInHeader"], "the switch is not in the Travel card's header"
    assert lab["noToggleOnCrewRows"], (
        "a crew row offers the auto/manual toggle — clicking it would overwrite that row's own "
        "Guys with the man-day sum")
    assert lab["linkishGone"], "the old underlined-link markup is still being rendered"
    assert ".labsw" in html, "the page no longer defines the switch's own style"
    assert ".linkish" not in html, "the old link style is still on the page"
    assert ".labtoggle" not in html, "the old flipping-button style is still on the page"


@needs_node
def test_the_switch_reports_its_state_instead_of_naming_the_next_action(ran):
    """What makes it a switch rather than a restyled button.

    Mutation: put the label back to flipping between "Type my own" and "Back to auto", and
    `labelOnce`/`backToAutoGone` go red."""
    both = ran["labor"]["toggleSaysItsState"]
    # BOTH POSITIONS. Travel boots in auto, so checking only the page as-built reads one
    # branch of the ternary and the other can say anything at all.
    for state in ("off", "on"):
        s = both[state]
        assert s["checked"], (
            "aria-checked is wrong with the switch %s" % state)
        assert s["labelOnce"] == 1, (
            "expected the one unchanging label with the switch %s, found %d copies"
            % (state, s["labelOnce"]))
        assert s["backToAutoGone"], (
            'the control still flips its words to "Back to auto" with the switch %s' % state)
        assert s["hasTrack"], (
            "the switch renders without the track the other switches use, %s" % state)


@needs_node
def test_the_switch_is_still_a_button_so_the_keyboard_still_reaches_it(ran):
    """The `.mw-sw` conditions on this page are <span role="switch"> with tabindex and NO
    keydown handler, so Space and Enter do nothing on them. This control was a real <button>
    and worked from the keyboard; matching the others visually must not quietly cost it that.

    Mutation: render it as a <span class="mw-sw labsw">."""
    assert ran["labor"]["toggleIsAButton"], (
        "the Guys switch is no longer a <button> — Space and Enter will not operate it")


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
    assert lab["afterDelete"] == ["Polishing", "Travel", "Densify"], (
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
    # `fees` is NOT in this list, and `contingency` never was: both are typed by the estimator
    # rather than computed, so neither has a keyed money cell to compare -- they are boxes. The
    # Fees line joined them on 2026-09-16; its own coverage is
    # test_the_fees_line_is_typed_and_marked_up_the_way_the_sheet_marks_it_up.
    for key in ("material", "shipping", "material_total", "labor", "escalation", "burden",
                "labor_total", "sub_total", "gp", "hard_bid", "super_pto", "soft_costs",
                "sales_tax", "remodel_tax", "taxes", "bond", "fees_and_bond", "total"):
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
    assert o["rowClasses"]["hard_bid"] == "off"
    # Hard bid OFF says nothing — the switch beside it already did. Hard bid ON with the bid still
    # under the threshold is the case that reads like a bug, so that is the case that gets words.
    assert not o["thresholdNoteWhenOff"], (
        "the hard bid row explains a threshold that is not why the discount is missing")
    assert o["thresholdNoteWhenOnButZero"], (
        "hard bid is on and the discount is zero, and the row does not say why")
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
        "Material Total", "Labor Total", "Total taxes", "Total fees + bond"], (
        "the bold closing rows are not the totals: %r" % ran["review"]["totalRowLabels"])


# ── E2. the Review step answers its own questions ────────────────────────────
@needs_node
def test_every_condition_review_talks_about_is_a_real_switch_here(ran):
    """Hanz, 2026-09-15: "any condition toggle present in BOTH Intake and Review should become a
    real, clickable toggle in Review."

    Review named five conditions and could set none of them — Sales tax and Remodel tax carried an
    "off · edit in Intake" link, Hard bid and Labor escalation carried a bare "off"/"prevailing
    wage off", and Bond carried nothing at all. An estimator reading the markup block and spotting
    a wrong flag had to leave the page, flip it, and come back.

    `local` is deliberately NOT here: it is an Intake toggle Review never mentions (it dims the
    Travel row on the Labor step), so it fails the "present in both" test this exists to satisfy.

    Mutation: render the label without `data-cond`. Every switch still draws, and not one of them
    does anything when clicked."""
    sw = ran["review"]["switches"]
    assert sorted(sw) == ["bond", "hard_bid", "prevailing_wage", "remodel_tax", "taxable"], (
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
    assert "Travel" in z["labels"], (
        "an unpriced Travel row is still missing from Review: %r" % z["labels"])
    assert "Joint filler" not in z["labels"], (
        "an unpriced non-travel row was listed: %r" % z["labels"])
    # And the priced row beside them is unaffected -- the change is about zeros, not about order.
    assert z["labels"][0] == "Polishing" and z["labels"][1] == "Travel", (
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

    Mutation: seed the row without `kind`."""
    m = ran["materialRow"]
    assert m["isItemKind"], "the added row is not marked as a material row"
    assert m["saysMaterial"], "a material row is indistinguishable from an assembly row on screen"
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

    Mutation: drop `coverage: r.coverage` from priceMaterialRow, and the typed figure collapses
    back to the library one."""
    m = ran["materialRow"]
    assert m["costWithLibraryCoverage"] == "$1,100", (
        "the row did not price off the item's own coverage: %r" % m["costWithLibraryCoverage"])
    assert m["costWithTypedCoverage"] == "$2,100", (
        "a coverage typed on the row did not reach the engine: %r" % m["costWithTypedCoverage"])
    assert m["costWithLibraryCoverage"] != m["costWithTypedCoverage"], (
        "both coverages priced the same, so the row's own box changes nothing")


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
    # A CARD EACH, the same `.tk` container the assembly rows use. Hanz: "at least make it a
    # container the same as the assemblie". Three bare switches under a column of cards read as
    # page furniture -- something that configures the list rather than something in it.
    c = ran["movedToTakeoff"]["cards"]
    assert c["count"] == 3, "expected three condition cards, found %s" % c["count"]
    # JOINT FILLER AND DYE CLAIM A COST, SINCE 2026-09-18. Before that date this said the
    # opposite -- "the card must not claim a cost" -- because neither priced anything: Hanz,
    # on staging, pointing at this exact step: "die and joint filler are supposed to be
    # materials not something that is default". The kits ARE charged, by Polish!E29, and now
    # by this screen too, so the card has to say so or the Material total above it disagrees
    # with its own line items. Joint Filler ships ON: 17,500 SF (this fixture's takeoff) is
    # exactly 5 kits of 3,500 at $500 -- $2,500. Dye ships OFF and gets the SAME unpriced-row
    # dash rowCost() already uses -- never "$0", which would read as a computed zero rather
    # than "not currently included".
    jf = c["jointFillerCost"]
    assert jf and not jf["empty"] and jf["text"] == "$2,500", (
        "Joint Filler ships on and prices 17,500 SF at one kit per 3,500 -- the card should "
        "read $2,500, got %r" % jf)
    dy = c["dyeCost"]
    assert dy and dy["empty"] and dy["text"] == "\u2014", (
        "Dye ships off and must show the unpriced-row dash, not a figure: %r" % dy)
    # REMOVE EXISTING IS THE ONE CARD THIS FEATURE MUST LEAVE ALONE -- it is a labor
    # modifier priced on the Labor step, and claims no dollar figure of its own here.
    assert c["removeExistingHasNoCostBox"], (
        "Remove Existing renders a cost box, which says it priced something it did not -- "
        "its price is on the Labor step")
    assert c["namesItsCell"], (
        "the cards do not name the cells they set, which is one of the things they do")


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
    # EIGHT CONDITIONS' CELLS NOW, and nothing else. local and hard_bid each carry a Polish
    # mirror; prevailing_wage, taxable and remodel_tax are formulas on the Polish tab and must NOT
    # be written there.
    #
    # E25/E29/F29 joined on 2026-09-16, when dye, joint filler and remove-existing moved off the
    # intake form onto the Takeoff step. Their cells did not change and neither did their
    # literals -- only which screen asks the question. They were written by polish-intake.js's own
    # `carry` loop before, from exactly one page; they go through the shared writer now because
    # two screens can answer them.
    assert ran["save"]["cellValueKeys"] == [
        "Epoxy!B4", "Epoxy!B5", "Epoxy!B6", "Epoxy!D5", "Epoxy!D6",
        "Polish!B4", "Polish!B5", "Polish!E25", "Polish!E29", "Polish!F29"], (
        "the save's worksheet cells are not exactly the eight conditions': %r"
        % ran["save"]["cellValueKeys"])
    # And the literals are the model's own answers. The fixture has local and taxable on, the other
    # three off, so a mapping written backwards cannot pass this.
    assert ran["save"]["cellValues"] == {
        "Epoxy!B4": "Yes", "Polish!B4": "Yes",      # local
        "Epoxy!B5": "No", "Polish!B5": "No",        # hard_bid
        "Epoxy!D5": "No",                           # prevailing_wage
        "Epoxy!B6": "Yes",                          # taxable
        "Epoxy!D6": "No",                           # remodel_tax
        # Joint filler ships ON and the other two off, which is freshModel's answer and was the
        # intake toggles' answer before it. BOTH LITERALS ARE ALWAYS WRITTEN, including
        # remove_existing_jf's "No" while joint filler is on: a blank Yes/No cell is not "No" to
        # Kyle's formulas, it is whatever his IF() falls through to.
        "Polish!E25": "No",                         # dye
        "Polish!E29": "Yes",                        # joint_filler
        "Polish!F29": "No",                         # remove_existing_jf
    }, "the condition literals do not match the model: %r" % (ran["save"]["cellValues"],)
    # A draft that already carried a worksheet map keeps it, and gains only those same five.
    carried = ran["save"]["legacyCellValues"] or {}
    assert set(carried) == {"Polish!D82", "Epoxy!B4", "Epoxy!B5", "Epoxy!B6", "Epoxy!D5",
                            "Epoxy!D6", "Polish!B4", "Polish!B5",
                            "Polish!E25", "Polish!E29", "Polish!F29"}, (
        "the page added a worksheet cell beyond the five conditions', or dropped a carried one: %r"
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
    # The five the draft DID state come across untouched, which is the half that matters: a
    # migration that reset a v1 job's answers would change a bid that has already been sent.
    assert m["conditions"] == {"local": False, "hard_bid": True, "prevailing_wage": True,
                              "taxable": False, "remodel_tax": True, "bond": False,
                              "dye": False, "joint_filler": True,
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
    assert m["keys"] == ["conditions", "contingency", "fees", "labor", "takeoff", "totals",
                         "version"], (
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

    THE BRITISH SPELLING IS THIS TEST'S WHOLE SUBJECT, so neither the name above nor the pattern in
    the harness's `offenders()` may be swept along by a labour->labor rename. Pointed at "labor"
    instead, it asserts the page never says the word it is supposed to say in a dozen places, and
    goes red everywhere at once — which is exactly what happened the first time this rename ran.

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
    # /js/icons.js is FIRST, ahead of auth.js: the sidebar auth.js draws asks it for every glyph
    # in the rail. See the house rule at the top of frontend/js/icons.js.
    assert srcs == ["https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.0",
                    "/js/icons.js", "/auth.js", "/shared.js", "/js/tab-memo.js",
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
    # $1,529 before 2026-09-18 -- joint_filler ships ON and now adds $2,500 to the material
    # this fixture prices, which moves the sub-total and, through it, GP and this remodel line.
    assert c["money"] == "$1,715" and c["expectedMoney"] == 1715
    assert c["total"] == "$38,541" and c["expectedTotal"] == 38541, (
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
    # $1,247 before 2026-09-18 -- same joint_filler-priced-by-default shift as the county case.
    assert f["money"] == "$1,398" and f["expectedMoney"] == 1398
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
    assert n["onScreen"] == ["Polishing", "Mock-up", "Joint filler", "Travel",
                             "Densify", "Night shift premium"], (
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
    assert f["onScreen"][-2:] == ["Densify", "Night shift premium"]


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
    assert w["onScreen"] == ["Polishing", "Mock-up", "Travel", "Densify"], (
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
    assert d["onScreen"] == ["Polishing", "Mock-up", "Travel", "Densify"]
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
    assert down["onScreen"] == ["Polishing", "Mock-up", "Joint filler", "Travel"], (
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

    EVERY STORED ANSWER IN THE FIXTURE DISAGREES WITH WHAT THE TOOL SHIPS -- joint filler ships ON
    and the library says off, dye and remove-existing ship off and the library says on. A fixture
    that agreed with freshModel would pass just as happily against a seeder that was never wired
    up at all.

    Mutation: delete the `if (conditionDefaults)` block from init(). Every new bid then opens with
    the shipped literals whatever anybody sets, and the Defaults tab is decoration."""
    c = ran["conditionDefaults"]["brandNew"]
    assert c["fetched"], "a blank bid never asked for the stored answers"
    assert c["conditions"]["joint_filler"] is False, (
        "the library's 'off' did not reach a brand new bid, so the Defaults tab changes nothing")
    assert c["conditions"]["dye"] is True
    assert c["conditions"]["remove_existing_jf"] is True
    # The five answered on Intake are not this tab's to move.
    assert c["conditions"]["taxable"] is True and c["conditions"]["local"] is True


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
    leaves behind (Polish!E29=Yes, Polish!E25=No, Polish!F29=No), and the library's stored default
    is the OPPOSITE of every one of them. A fixture that answered only one of the three could pass
    against a page that seeded the other two from the library regardless of what their cells said.

    Mutation: swap the two calls in init() so seedConditionDefaults runs outermost. All three then
    come back flipped and every cell answer the estimator gave is gone."""
    c = ran["conditionDefaults"]["celled"]
    assert c["fetched"], "the library was never asked for its stored answers"
    assert c["dye"] is False, (
        "the library's answer was written over the 'No' already in Polish!E25")
    assert c["jointFiller"] is True, (
        "the library's answer was written over the 'Yes' already in Polish!E29")
    assert c["removeExistingJf"] is False, (
        "the library's answer was written over the 'No' already in Polish!F29")


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
