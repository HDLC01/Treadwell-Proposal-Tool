"""The BETA polish intake form, executed out of the real frontend/js/polish-intake.js.

WHAT HANZ ASKED FOR.

2026-08-17, on the beta calculator dropping from seven sub-steps to three: "The conditions we move
them to the intake form (For Beta Only). Intake form of Beta and Active projects should be separate
for now, since this is for testing." And, on the toggles themselves: "Keep them as toggle buttons."

So there are two intake forms. This one is small on purpose — a test harness for the beta polish
calculator, not a second copy of index.html — and it owns the job conditions that used to be the
calculator's step 2.

IT ASKS SIX QUESTIONS AND WRITES TWELVE WORKSHEET CELLS, which is the shape to hold in mind
while reading the rest.
Five of the six are engine conditions stored on polish_estimate.conditions; the sixth,
Renovation, has no home on the model and lives only in cell_values. Three MORE — dye, joint filler
and remove-existing — are answered on the Takeoff step since 2026-09-16 and are not on this screen
at all, and this page still writes their Yes/No into Kyle's workbook on every save, because
cell_values is what the downloaded .xlsx is filled from. That last sentence is the one the tests
below spend the most effort on: it is the half of the move that can fail with every screen still
looking right.

Hard bid was a seventh question here until 2026-09-22, when Hanz asked for it removed from the
Polish beta entirely: "remove all hard bids from the polish intake form. And also on the
markups." It priced a discount for bidding against a hard number rather than a budget — see
polish-bid-core.js's removal notes for the formula it used to feed.

WHY EXECUTED, NOT GREPPED.

House rule, and it was bought: STAGE_CREATED took the board down on prod on 2026-08-12 with every
source assertion in the suite green, because a source-text assertion cannot see an unbound
identifier or a transposed write. The failures that matter on this page are all of that shape:

  * "the save merges into polish_estimate" is a claim about an OBJECT. It fails as a finished
    takeoff disappearing when somebody flips a toggle, and the only honest check is to put takeoff
    rows on the model, flip a toggle, and read what was queued.
  * `paintCondition` finds its switch by `#cond-<key>`, an id `switchHtml` writes in a different
    function. Grepping proves both mention it; rendering and then clicking proves the repaint lands
    on the element the page produced.
  * "nothing renders before the sandbox settles" is an ORDERING, checked as one.

The condition KEYS are compared with the real js/polish-bid-core.js, whose markupChain() reads them
by key to decide the hard-bid discount, the labor escalation and the two taxes. A key that drifted
here would be a prevailing-wage job quietly priced at standard rates, and nothing on screen would
say so.

The page also owns the COUNTY, which is the sixth thing that moves the price and the only one that
is not a toggle — see the section on it further down for why it is a job condition, what four draft
keys it writes, and why 10% must not appear anywhere on the page.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "polish-intake-harness.js"

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
    return (FRONTEND / "polish-intake.html").read_text(encoding="utf-8")


# ── the six toggles this form asks ──────────────────────────────────────────
@needs_node
def test_a_polish_job_renders_six_conditions_as_toggles(ran):
    """SIX switches, in the order the live intake shows them for a polish job, each a toggle.

    IT WAS TEN UNTIL 2026-09-16, and the three that left are the point of this number. Hanz,
    2026-09-11: "ytou didnt follow this on the beta polish, the toggle buttons are different for
    each work type." js/index.js scopes ten conditions by work type and hands a polish job nine of
    them; this page shipped a flat five, so an estimator who set Renovation or Dye on the live
    intake arrived here to find the questions missing. All nine went on. Then Hanz asked for the
    three that describe the WORK — Dye, Joint filler, Remove existing joint filler — to sit on the
    Takeoff step, where the work is actually described, rather than among questions about the
    building and the bid. They are pinned there by
    test_polish_estimate_page.py, and the cells they still write are pinned below.

    IT WAS SEVEN UNTIL 2026-09-22. Hard bid was one of the engine five until then, priced as a
    discount off the bid for a job the customer will award on the lowest number rather than a
    negotiated budget. Hanz: "remove all hard bids from the polish intake form. And also on the
    markups" — scoped to the Polish beta only, controls and data both. There is no toggle left for
    it anywhere on this screen; see polish-bid-core.js and markup.js for what its removal took out
    of the pricing chain.

    What is LEFT here is the four the engine prices plus Bond plus Renovation, and Renovation is
    the one worth explaining rather than leaving to be rediscovered: it is not a description of
    the work, it is a fact about the building — an existing floor rather than new construction.
    That is an intake question, asked once, before anybody opens a takeoff.

    Bond is this page's own — the live intake has no Bond question because the workbook's bond rate
    is a hardcoded cell, not a Yes/No flag. It is here so the Review step's Bond row has a control
    instead of a permanently dead "off", and it moves no money: see
    test_polish_estimate_page.test_bond_is_a_switch_that_changes_no_number.

    Mutation: drop back to the engine four, or reorder them, or put the three moved ones (or hard
    bid) back. Any of those makes two screens ask the same question, or asks one nobody can answer
    any more, either of which is the state this change ended."""
    keys = [s["key"] for s in ran["conditions"]["rendered"]]
    assert keys == ["local", "prevailing_wage", "taxable", "remodel_tax", "bond", "reno"]
    assert [s["label"] for s in ran["conditions"]["rendered"]] == [
        "Local job", "Prevailing wage", "Taxable", "Remodel tax", "Bond", "Renovation"]
    assert ran["conditions"]["allAreSwitches"], "a condition rendered without its toggle track"
    assert ran["conditions"]["allHaveWhy"], (
        "a toggle lost its plain-English line — 'Prevailing wage' on its own tells an estimator "
        "nothing about what it does to the price")
    # And the three really are gone from this screen, asked of the rendered block rather than
    # inferred from the list above. "They moved" is only true if they left.
    assert ran["moved"]["stillOnScreen"] == [], (
        "dye/joint filler/remove-existing are still on the intake form as well as the Takeoff "
        "step, so an estimator can answer the same question twice: %r"
        % ran["moved"]["stillOnScreen"])


@needs_node
def test_the_keys_are_the_ones_the_pricing_engine_reads(ran):
    """markupChain() in polish-bid-core.js looks each condition up BY KEY and a miss reads as
    `false`. Two lists, one contract — pinned against the real module so they cannot drift.

    Mutation: rename `remodel_tax` to `remodel` here. The toggle still works, still saves, still
    reads back — and the remodel tax silently never reaches the bid.

    THE TWO SETS STOPPED BEING EQUAL ON 2026-09-16, and the shape of the inequality is the
    assertion. Before that, every key on the model was a switch on this form. Now the model carries
    three more than this form renders, because dye, joint_filler and remove_existing_jf moved into
    it when they moved onto the Takeoff step — they are answered there and stored on the model, and
    this page writes their cells without asking about them. So the rule is CONTAINMENT, not
    equality: nothing this form renders may be missing from the model (that is a toggle that saves
    nowhere), and the only keys the model may have beyond it are those three (anything else is a
    condition nobody can answer).

    `pageKeys` is the FIVE the model stores for this form, not the four the chain reads: `bond`
    lives on the model so the Review step's switch has somewhere to write, and markupChain() never
    looks it up — bond_pct is RATES.BOND unconditionally. That is deliberate and pinned separately,
    so do not read this as "the engine reads all five"."""
    page, core = ran["conditions"]["pageKeys"], ran["coreKeys"]
    assert page == ["local", "prevailing_wage", "taxable", "remodel_tax", "bond"]
    assert set(page) <= set(core), (
        "this form renders a condition the model has no key for, so it saves nowhere: %r"
        % (set(page) - set(core)))
    assert set(core) - set(page) == {"dye", "joint_filler", "remove_existing_jf"}, (
        "the model carries a condition neither this form nor the Takeoff step asks about: %r"
        % (set(core) - set(page)))
    # SIX RENDER, FOUR PRICE. Renovation is on screen and not on the model at all — it is a cell
    # in Kyle's workbook, not an input to this page's library-based engine, and folding it into
    # CONDITIONS to shorten the code would break this count.
    assert len(ran["conditions"]["rendered"]) == len(page) + 1, (
        "the screen and the engine drifted apart")


@needs_node
def test_the_documented_defaults_are_what_a_new_project_shows(ran):
    """Most jobs are local and taxable; the other three are the exceptions somebody has to know
    about. A brand-new project has no model at all, so these have to come from this page.

    Read off freshModel().conditions rather than restated here, which is why NINE keys come back
    from a form that renders six of them: dye, joint_filler and remove_existing_jf joined the model
    on 2026-09-16 and are answered on the Takeoff step. They are in this assertion anyway, because
    this page writes their cells on every save and a default that drifted here would be the answer
    a brand-new project's workbook got.

    Mutation: default everything to false, and every beta bid quietly loses its sales tax — and
    with joint_filler flipped, every polish bid loses a kit per 3,500 sq ft."""
    # joint_filler moved to False on 2026-09-19, with index.js's own `def` and freshModel's
    # literal flipped together: the line charges a $500 kit per 3,500 sq ft, and leaving it on by
    # default put $2,500 nobody had chosen into a 17,500 SF bid. The two copies of this answer
    # MUST agree -- this screen writes Polish!E29 the instant any switch is touched, so a stale
    # True here would put the kit back into Kyle's workbook on the live intake path alone.
    assert ran["conditions"]["defaults"] == {
        "local": True, "prevailing_wage": False,
        "taxable": True, "remodel_tax": False, "bond": False,
        "dye": False, "joint_filler": False, "remove_existing_jf": False}
    # Local + Taxable on, the other four off — the live intake's defaults, which are how Kyle's
    # sheet ships. Bond off matches B78 shipping at zero.
    assert ran["conditions"]["freshRender"] == [
        ["local", True], ["prevailing_wage", False],
        ["taxable", True], ["remodel_tax", False], ["bond", False],
        ["reno", False]]


@needs_node
def test_a_v1_model_still_has_its_conditions_read(ran):
    """A draft priced before the rework carries {areas: […]} with no `version`, and its conditions
    in the same shape. Defaults fill only what it does not state.

    Mutation: read conditions only when `version` is set, and every older beta project silently
    reverts to local + taxable — including the prevailing-wage ones."""
    assert ran["conditions"]["v1Render"][:4] == [
        ["local", False], ["prevailing_wage", True],
        ["taxable", True], ["remodel_tax", False]]
    # Bond and Renovation are NOT in polish_estimate.conditions on a v1 draft and never were, so
    # such a model states nothing about them and they show their documented defaults. Renovation
    # comes back from cell_values instead — test_renovation_comes_back_from_its_cells. Bond has no
    # cell to come back from, so `false` is the whole of its story on an older draft.
    #
    # The three that moved are not in this list because they are not on this screen any more; what
    # a v1 draft does about THEM is migrateModel's generic backfill, pinned in
    # test_polish_markup_parity.test_a_v1_draft_opens_as_a_v2_model.
    assert ran["conditions"]["v1Render"][4:] == [
        ["bond", False],
        ["reno", False]]


@needs_node
def test_the_spreadsheet_cell_chips_are_gone(ran):
    """B4/B5/D5/B6/D6 were on the calculator's panel, where Kyle could check a field against the
    workbook. This page writes the draft, not the workbook, so a cell name here points at
    something it never touches."""
    assert ran["conditions"]["noCellChips"], "a toggle still names a worksheet cell"


# ── renovation, the one condition this form still carries ────────────────────
#
# Hanz picked "Mirror v1, carry through only" on 2026-09-11: the beta asks the same nine questions
# a polish job gets on the live intake and writes all nine into the draft, so both screens agree
# and the sheet and the proposal read them — while the beta's own library-based price stays exactly
# as it was. Four of the nine were CARRIED rather than priced, in a list of their own outside the
# model, because migrateModel() would have dropped them.
#
# THREE OF THOSE FOUR MOVED ON 2026-09-16 and are no longer carried at all: they live on the model
# now and are answered on the Takeoff step. The section after this one is about them, and it is the
# one that matters — moving a question is easy, and keeping its answer in Kyle's workbook while the
# question moves is the part that can silently fail.
#
# `reno` stayed, and stayed carried, for the reason it always was: it is not one of
# freshModel().conditions, so migrateModel() whitelists it straight out of any model it is stored
# on. cell_values is its one home.
@needs_node
def test_renovation_is_the_only_condition_this_form_carries(ran):
    """One key, and it is Renovation.

    Mutation: add bulk_discount. It is epoxy/combo on the live intake — see
    test_intake_conditions.py — and a polish estimator would be answering a question that does not
    apply to the job. Or put dye back: the Takeoff step already asks it, and two screens writing
    Polish!E25 out of two different objects is how they come to disagree."""
    assert ran["carry"]["keys"] == ["reno"]


@needs_node
def test_renovation_writes_both_literals_into_both_cells_on_every_save(ran):
    """Both cells, on EVERY save, with an explicit literal for off — never a blank.

    Polish!C17 is IF(B10="New",0.05,0.15): an empty B10 silently takes the Reno branch and triples
    the patch material rate. And Epoxy!B10 is written alongside Polish!B10 because it is the cell
    the live intake hydrates Renovation FROM (js/index.js reads cells[0]) and the cell the AI
    autofill writes its New/Reno answer to — writing only the Polish one would leave this page
    agreeing with the workbook and disagreeing with the two screens either side of it.

    The `offCells` half is the one that needs the whole sentence "on every save": it is read off a
    save this page made for an UNRELATED reason, before Renovation had been touched at all.

    Mutation: write only the toggle that was clicked, or leave "off" blank. The bid comes back with
    a tripled patch rate and nothing on screen to explain it."""
    assert ran["carry"]["offCells"] == {"Epoxy!B10": "New", "Polish!B10": "New"}, (
        "an untouched Renovation left its cells blank, which Kyle's IF() reads as Reno")
    assert ran["carry"]["onCells"] == {"Epoxy!B10": "Reno", "Polish!B10": "Reno"}
    # And the engine five still reach both of their homes, unchanged by any of this.
    assert ran["carry"]["engineCells"] == {
        "Epoxy!B4": "Yes", "Polish!B4": "Yes", "Epoxy!B6": "Yes"}
    assert ran["carry"]["savedOnce"], "one flip has to be one save"
    assert ran["carry"]["takeoffKept"] == 2, "a condition flip deleted the takeoff"


@needs_node
def test_renovation_stays_out_of_the_model(ran):
    """cell_values is its ONE home, and that is a constraint, not a preference.

    migrateModel() whitelists condition keys against freshModel().conditions and drops every other
    one, so a key stored in polish_estimate.conditions would look saved and come back missing on
    the next load — silently, on the estimator's second visit.

    THE SISTER TEST IS THE NEXT ONE, and the pair is worth reading together: dye, joint filler and
    remove-existing used to be asserted to stay out of the model for exactly this reason, and on
    2026-09-16 they were deliberately put IN it — by adding them to freshModel().conditions, which
    is what makes the whitelist keep them. Renovation was not, so it still cannot be stored there.
    The decision is "add the key to freshModel, or keep it in cell_values", never "store it and
    hope".

    Mutation: store `reno` in polish_estimate.conditions "so it is all in one place". This test
    goes red, and without it the bug only shows up as a toggle that will not stay set."""
    assert ran["carry"]["flippedInCarry"] is True
    assert ran["carry"]["notInTheModel"], "reno was written onto the pricing model"
    assert "reno" not in ran["carry"]["savedConditionKeys"]
    assert ran["carry"]["savedConditionKeys"] == ran["coreKeys"]
    # What the calculator gets handed back on the next load: the model's own keys, and still no
    # `reno` among them.
    assert ran["carry"]["readBackConditionKeys"] == ran["coreKeys"]


@needs_node
def test_renovation_moves_no_money_on_this_pages_engine(ran):
    """Carried, not priced. This page prices from the Items & Assemblies library; polish-bid-core
    has no notion of renovation (grep it — nothing comes back). In Kyle's workbook B10 really does
    move a price, which is the whole reason the cell has to be written correctly.

    ASKED OF THE ENGINE, NOT OF TWO SAVES. Comparing the model this page wrote before the flip with
    the one it wrote after would be vacuous by construction — `reno` is not a model key, so those
    two objects are equal whatever happens — and would stay green after somebody taught markupChain
    to read it. So the probe adds `reno` to the saved conditions and prices both.

    Mutation: hand `cond.reno` to markupChain. This goes red; without it the next person to add
    that branch would silently change every beta bid."""
    assert ran["carry"]["priceIdentical"], (
        "markupChain read `reno` — it is a workbook cell, not an input to this page's engine")
    # AND WITH THE ENGINE SIX THE OTHER WAY ROUND. The save this prices has Prevailing wage on,
    # because flipping it is what triggered the save — so a read written as `prevailing_wage ||
    # reno` would move no money in the run above and slip through. Pricing the same pair again with
    # every engine condition inverted takes that hiding place away.
    assert ran["carry"]["priceIdenticalInverted"], (
        "markupChain read `reno` behind a condition that happened to be on in the first run")
    assert ran["carry"]["priceTotal"] > 0, "the price probe priced nothing, so it proves nothing"


@needs_node
def test_renovation_comes_back_from_its_cells(ran):
    """It has nowhere else to come back from, so a reload reads it out of cell_values.

    Mutation: hydrate only the engine five. The estimator's Renovation flag resets to New on the
    next visit and the patch rate changes under them."""
    assert ran["carry"]["hydrated"] == [
        ["local", True], ["prevailing_wage", False],
        ["taxable", True], ["remodel_tax", False], ["bond", False],
        # Epoxy!B10 said Reno, which is the opposite of the documented default — so a hydrate that
        # quietly fell through to that default cannot produce this row.
        ["reno", True]]


# ── the three that moved, and the workbook cells they must still reach ───────
#
# THIS IS THE RISK THE 2026-09-16 MOVE CARRIES. Dye, joint filler and remove-existing used to be
# written into cell_values by this page's own `carry` loop, from this page alone. That loop is
# gone. Nothing on screen would notice if nothing had replaced it: the questions are still ASKED
# (on Takeoff), still SAVED (on the model) and still shown back there — and Polish!E25/E29/F29
# would quietly go blank in every workbook a save from THIS page touched. A blank Yes/No cell is
# not "No" to Kyle's formulas, it is whatever his IF() falls through to, so the downloaded bid
# would be wrong with every screen still right.
#
# What replaced the loop is B.conditionCellWrites, the one writer both screens call, driven by
# M.conditions. The probes below are round trips through the product: the answers are set the way
# the Takeoff step sets them, on the model, and the page is then saved for an UNRELATED reason.
@needs_node
def test_the_three_that_moved_still_write_their_cells_from_here(ran):
    """All three cells, both literals, out of a save this page made for another reason entirely.

    THE FIXTURES ARE THE ARGUMENT. `shipped` is how Kyle's sheet ships — joint filler on, the other
    two off. `flipped` is all three the other way, which puts Remove existing joint filler at YES
    while Joint filler is OFF: that is the combination the Takeoff step dims, and a dimmed switch's
    answer still has to reach the workbook, because dimming says "this moves no money here", not
    "nobody answered". `nothing` has joint filler and remove-existing both off, which is where
    F29's "No" is the write a tidy-up deletes on the grounds that it changes nothing.

    Mutation: make conditionCellWrites skip remove_existing_jf while joint_filler is off, or make
    it write only keys whose value is true. Either leaves a blank cell that Kyle's IF() does not
    read as "No", and every screen still shows the right answer."""
    assert ran["moved"]["shippedCells"] == {
        "Polish!E25": "No", "Polish!E29": "Yes", "Polish!F29": "No"}
    assert ran["moved"]["flippedCells"] == {
        "Polish!E25": "Yes", "Polish!E29": "No", "Polish!F29": "Yes"}, (
        "remove-existing's Yes did not reach the workbook while joint filler was off")
    assert ran["moved"]["nothingCells"] == {
        "Polish!E25": "No", "Polish!E29": "No", "Polish!F29": "No"}
    # WRITTEN AT ALL, which is a different claim from "equal to No". Once the key stops being
    # written, `undefined` is what every downstream reader sees, and it is falsy in exactly the
    # places "No" is — so the way this fails is invisible to a check that only compares values.
    cells = ["Polish!E25", "Polish!E29", "Polish!F29"]
    for which in ("shippedWritten", "flippedWritten", "nothingWritten"):
        assert ran["moved"][which] == cells, (
            "a condition cell stopped being written in the %r case: %r"
            % (which, ran["moved"][which]))


@needs_node
def test_the_three_that_moved_are_in_the_model_and_survive_the_read_back(ran):
    """THE INVERSION, and it is recorded here rather than left as a deleted test.

    Until 2026-09-16 this file asserted the OPPOSITE — that dye, joint_filler and
    remove_existing_jf must stay out of polish_estimate.conditions — and the reason was real:
    migrateModel() whitelists condition keys against freshModel().conditions and drops every other
    one, so storing a key that freshModel did not know about meant it looked saved and came back
    missing on the estimator's next visit.

    The move did not defeat that rule, it satisfied it. The three were ADDED to
    freshModel().conditions (polish-bid-core.js), which is what a key needs in order to be storable
    at all, and only then moved onto the Takeoff step. So the old assertion is not wrong about the
    mechanism, it is out of date about the list — which is why this test names both and asserts the
    read-back rather than just the write. Renovation, which was not added to freshModel, is still
    held to the old rule one section up.

    Mutation: take the three back out of freshModel().conditions while leaving the Takeoff switches
    writing them. Every answer looks saved, and every one of them is gone on the next load."""
    keys = ["dye", "joint_filler", "remove_existing_jf"]
    assert ran["moved"]["inTheModel"] == keys, (
        "a moved condition never reached the model, so the Takeoff switch writes nowhere: %r"
        % ran["moved"]["inTheModel"])
    assert set(ran["moved"]["savedConditions"]) == set(ran["coreKeys"]), (
        "the save's model conditions are not the engine's key set: %r"
        % sorted(ran["moved"]["savedConditions"]))
    # The blob the page actually saved, run back through migrateModel the way the next visit does.
    # The `flipped` fixture is the one used here because all three of its answers are the opposite
    # of freshModel's, so a read-back that silently reverted to the defaults cannot pass.
    assert ran["moved"]["readBack"] == [
        ["dye", True], ["joint_filler", False], ["remove_existing_jf", True]], (
        "migrateModel dropped or reset a moved condition on the way back in: %r"
        % ran["moved"]["readBack"])


@needs_node
def test_the_three_that_moved_still_come_back_from_their_cells(ran):
    """A project that has cells and no model at all — one that came through the live intake — still
    arrives on this page with all three answered.

    Their read-back used to be a second loop, over CARRY_CONDITIONS, sitting beside the engine
    five's. It is one loop over CONDITION_CELLS now, which is what makes "the cell wins where there
    is one" true of all eight rather than of five.

    Mutation: hydrate only the keys this form renders. The three revert to freshModel's answers on
    arrival, and this page's own save then writes those defaults back over the estimator's."""
    assert ran["moved"]["hydrated"] == [
        # Polish!E25 Yes, Polish!E29 No, Polish!F29 Yes — every one the opposite of the default,
        # so a hydrate that never ran cannot produce this.
        ["dye", True], ["joint_filler", False], ["remove_existing_jf", True]]


@needs_node
def test_the_three_that_moved_still_move_no_money(ran):
    """A NEW RISK, not an old reassurance, and that is why this test grew rather than shrank.

    Until 2026-09-16 these three were physically incapable of changing the beta price: they were
    not on the model, and the model is what markupChain() is handed. They are on it now. So "they
    price nothing" stopped being a fact about the data shape and became a claim about the engine —
    one line of `if (cond.joint_filler)` away from being false, in the object the chain already
    reads.

    Proven over two saves this page really wrote, which differ in nothing but these three keys.
    Dye's beta price is a starred default assembly on the estimate screen, decided separately; a
    second charge for it here would double it.

    Mutation: add a joint-filler branch to markupChain. This goes red."""
    assert ran["moved"]["priceIdentical"], (
        "flipping the moved conditions moved the beta price — these are workbook cells, not "
        "inputs to this page's engine")
    # AND WITH THE ENGINE SIX THE OTHER WAY ROUND. Found by mutation, not by reasoning: the first
    # version of this test stayed GREEN with `cond.joint_filler` wired into the labor escalation,
    # because both saves have Prevailing wage on — flipping it is what triggers them — and the
    # branch was an OR with prevailing_wage. Pricing the same pair again with every engine
    # condition inverted removes that hiding place.
    assert ran["moved"]["priceIdenticalInverted"], (
        "markupChain read a moved condition behind another that happened to be on in the first run")
    assert ran["moved"]["priceTotal"] > 0, "the price probe priced nothing, so it proves nothing"
    # NOT A VACUOUS PAIR. The two saved condition sets have to really disagree about all three, or
    # "the price did not move" is a statement about two identical inputs.
    assert ran["moved"]["pricedInputsDiffer"] == [
        "dye", "joint_filler", "remove_existing_jf"], (
        "the two priced fixtures do not actually differ, so the comparison proves nothing: %r"
        % ran["moved"]["pricedInputsDiffer"])


@needs_node
def test_flipping_a_toggle_here_never_throws_away_the_caret(ran):
    """These are keyboard-reachable (role="switch", tabindex), and re-rendering the block throws
    away whatever the estimator had tabbed into. A browser walk found that class of bug once
    already — see the note in polish-intake.js; no unit test reaches for the keyboard unless it is
    written to.

    WHAT THIS REPLACED, and why it is not simply gone. Until 2026-09-16 the test here was
    test_flipping_joint_filler_puts_the_caret_back: Joint filler changed the SENTENCE inside the
    switch below it, so flipping it re-rendered the whole block, and the assertion was that the
    page put the caret back afterwards. Joint filler and its dependent both moved to the Takeoff
    step, and with them the only `needs` rule on this form — so there is no longer a switch here
    that CAN force that re-render, and a test driving it would be driving nothing.

    repaintCondition's block branch is kept rather than deleted, because the rule it implements is
    generic and CARRY_CONDITIONS is a list somebody will add to again. So what is pinned now is the
    state that makes the cheap path the only one: no entry asks to be greyed out by another, and a
    flip repaints one element in place while the caret stays where the estimator put it.

    Mutation: make repaintCondition always call renderConditions(). The caret jumps off Local job,
    and nothing on screen looks wrong."""
    assert ran["caret"]["dependsOn"] == [], (
        "a condition on this form depends on another again — it will re-render the whole block on "
        "every flip, so restore the caret the way repaintCondition does and test it: %r"
        % ran["caret"]["dependsOn"])
    assert ran["caret"]["focusUnmoved"] == "cond-local", (
        "flipping Taxable moved the caret off the switch the estimator had tabbed into")
    assert ran["caret"]["containerUntouched"], (
        "the whole conditions block was re-rendered to record one flip")
    assert ran["caret"]["elementRepainted"] == "sw", (
        "the cheap path did not repaint the element it was aimed at")


# ── clicking one ─────────────────────────────────────────────────────────────
@needs_node
def test_clicking_a_toggle_flips_the_model_and_queues_a_save(ran):
    """The page's own delegated click handler, fired at the element renderConditions produced.

    Mutation: paint the switch and forget the save. It looks completely right on screen and the
    flag is gone the moment the page is left."""
    t = ran["toggle"]
    assert t["flippedInTheModel"] is True, "the click never reached the model"
    assert t["debounced"], "the save is not queued on the 600ms timer the calculator uses"
    assert t["savedOnce"] and t["savedValue"] is True, (
        "the queued save does not carry polish_estimate.conditions.prevailing_wage")
    assert t["repaintedOn"] == "sw on" and t["repaintedAria"] == "true", (
        "the switch that was clicked does not show it — paintCondition addresses an element "
        "renderConditions never rendered")
    assert t["flipsBack"] is False and t["repaintedOff"] == "sw", (
        "a second click does not turn the condition back off")


@needs_node
def test_a_toggle_does_not_delete_the_takeoff(ran):
    """THE REGRESSION THIS PAGE COULD CAUSE. `takeoff`, `labor`, `areas` and the rest of the
    calculator's model live under the SAME `polish_estimate` key. Recording one toggle by writing
    {conditions: …} over the top of that object deletes a finished takeoff, silently, and nobody
    finds out until the bid comes back at zero.

    Mutation: `polish_estimate: {conditions: M.conditions}`."""
    t = ran["toggle"]
    assert json.loads(t["takeoffKept"]) == [
        {"assembly_id": "asm-sp", "assembly_name": "Salt & Pepper polish",
         "measurement": 12500, "unit": "SF"},
        {"assembly_id": "asm-edge", "assembly_name": "Edge grind",
         "measurement": 900, "unit": "LF"}], (
        "the takeoff rows did not survive flipping a toggle")
    assert json.loads(t["laborKept"]) == [
        {"id": "polishing", "label": "Polishing", "guys": 4, "days": 3, "rate": 32.2},
        {"id": "mockup", "label": "Mock-up", "guys": 3, "days": 0.5, "rate": 32.2},
        # Backfilled by migrateModel() at boot (#491's Travel row, added after this fixture's
        # labor array was written) — not something a toggle-save is expected to have dropped.
        {"id": "travel", "label": "Travel", "guys": "", "days": "", "rate": 33,
         "unit": "hours", "guys_auto": True}], (
        "the labor rows did not survive flipping a toggle")
    assert t["versionKept"] == 2, "the model's version was dropped by an intake save"
    # And the three conditions nobody touched are still what they were.
    assert t["siblingConditions"] == [
        ["local", True], ["taxable", True], ["remodel_tax", False]]


@needs_node
def test_a_model_with_no_conditions_at_all_keeps_its_takeoff_too(ran):
    """The same merge, from the other direction: a draft whose polish_estimate holds only a takeoff
    has conditions ADDED to it, not substituted for it."""
    t = ran["takeoffOnly"]
    assert json.loads(t["takeoff"]) == [
        {"assembly_id": "asm-sp", "assembly_name": "Salt & Pepper polish",
         "measurement": 12500, "unit": "SF"},
        {"assembly_id": "asm-edge", "assembly_name": "Edge grind",
         "measurement": 900, "unit": "LF"}]
    assert json.loads(t["labor"]) == [
        {"id": "polishing", "label": "Polishing", "guys": 4, "days": 3, "rate": 32.2},
        {"id": "mockup", "label": "Mock-up", "guys": 3, "days": 0.5, "rate": 32.2},
        # Backfilled by migrateModel() at boot — see the sibling test above.
        {"id": "travel", "label": "Travel", "guys": "", "days": "", "rate": 33,
         "unit": "hours", "guys_auto": True}]
    assert t["taxable"] is False, "the clicked toggle did not land"
    assert t["local"] is True, "the untouched defaults did not land alongside it"


@needs_node
def test_two_flips_in_one_window_send_one_save_carrying_both(ran):
    """Debounced, not dropped. Mutation: re-arm without merging, and the first flip is lost."""
    assert ran["toggle"]["coalesced"] == 1
    assert ran["toggle"]["coalescedBoth"], "one of the two flips never reached the server"


@needs_node
def test_the_beta_is_polish_and_the_city_is_kept_combined(ran):
    """`work_type` decides which estimate tab and which proposal template the tool uses, and the
    beta calculator is polish-only. `city_state` is the one field the estimate sheet (C3), the
    proposal's {{city_state}} and the tax lookup all read, so this form composes it the way the
    live intake does — including upper-casing a state typed in lower case."""
    assert ran["toggle"]["workType"] == "polish"
    assert ran["toggle"]["cityState"] == "Kansas City, KS"


@needs_node
def test_a_condition_answered_on_review_survives_a_trip_to_intake(ran):
    """THE BUG THIS PAIR EXISTS FOR, found by audit on 2026-09-15 and fixed the same day.

    The Review step gained clickable condition switches, and for one commit it wrote only
    `polish_estimate.conditions` — not the Yes/No cells. This page's adoptModel lets the CELL win
    over the model ("THE CELL WINS WHERE THERE IS ONE"), a rule that is only safe while every
    writer writes both, which its own comment says outright: "the cell can never be the staler of
    the two."

    So: turn Sales tax off on Review, then follow either of Review's OWN links to this page —
    remodelSource()'s "pick a county", or the Labor step's "Change it on the intake step" — and
    Epoxy!B6 still said "Yes", so the estimator got their old answer handed back. Touch anything
    here and save() wrote the model from it, making the revert permanent. A silently reverted
    `taxable` moves the bid by 9.475% of materials, on a screen whose job is to be trusted.

    The fix is that the Review step writes those cells too, through the one shared
    `B.conditionCellWrites` — see test_polish_estimate_page.test_the_save_writes_the_condition_
    cells_and_no_others for the other half.

    NOT A VACUOUS PAIR, and `revertsWhenCellNotWritten` is what proves it: the same visit with the
    cell left saying "Yes" — exactly what the buggy version produced — still reverts. If the
    cell-wins rule ever stops running, that counterexample goes false and this test says so
    instead of passing for the wrong reason.

    Mutation: drop the cell_values line from polish-estimate.js's saveSoon. The harness's
    `fromReview` blob stops being reachable in the product, and this test keeps passing on a
    fixture the product can no longer produce — which is why the estimate page owns the assertion
    that it writes them."""
    rt = ran["roundTrip"]
    assert rt["revertsWhenCellNotWritten"] is True, (
        "the cell-wins rule is not running, so the rest of this test proves nothing")
    assert rt["taxableOnScreen"] is False, "the switch showed the answer Review replaced"
    assert rt["model"] is False, "the model was overwritten from a cell that agreed with it"
    # And passing through — setting some OTHER condition — must not write the old answer back.
    assert rt["savedModel"] is False, "a later save put the reverted answer back on the model"
    assert rt["savedCell"] == "No", "a later save put the reverted answer back in the cell"
    assert rt["theOtherOneLanded"] is True, (
        "the visit did not actually save anything, so nothing was proved about what it preserved")


@needs_node
def test_a_stray_condition_key_invents_nothing(ran):
    """Only the five. Mutation: write whatever `data-cond` says, and a sixth key lands in the model
    where cellWrites() will never look for it."""
    assert ran["strayKey"]["unchanged"], "an unknown data-cond was written onto the model"
    assert ran["strayKey"]["armed"] == 0, "an unknown data-cond still queued a save"
    assert ran["strayKey"]["plainClickIsQuiet"], (
        "a click anywhere on the page queues a save, so ordinary clicking writes to the server")


# ── Continue ─────────────────────────────────────────────────────────────────
@needs_node
def test_continue_goes_to_the_beta_estimate_carrying_the_draft(ran):
    """shared.js's _WIZARD_PATH excludes the beta pages, so nothing stamps ?d= on this button for
    us — TW.withDraft has to.

    Mutation: a bare "/polish-estimate.html". On a test copy the stored id can still be the REAL
    project's, and Continue would walk the estimator back onto the live bid."""
    c = ran["continue_"]
    assert c["wired"], "the form has no submit handler at all"
    assert c["prevented"], "the submit is not intercepted, so the browser posts the form"
    assert c["navigated"] == ["/polish-estimate.html?d=proj-1"]


@needs_node
def test_continue_saves_before_it_leaves(ran):
    """Not on the 600ms timer: a navigation kills a pending debounce, and the toggle the estimator
    flipped a moment before pressing Continue would never be written."""
    c = ran["continue_"]
    assert c["savedBeforeLeaving"], "Continue navigates with the save still on the timer"
    assert c["savedConditions"], "the save on the way out carries no conditions"


# ── Will's bug: switching tabs loses everything typed ───────────────────────
@needs_node
def test_typing_a_named_field_arms_the_save_but_the_county_search_box_does_not(ran):
    """wire() bound a delegated click, the submit, and the county box -- and nothing else. The
    eight named text fields were pure DOM until Continue, so a step-nav tab or a reload lost
    every one of them. #county-input has no `name`: its keystrokes are a live search
    (onCountyInput already saves the picked county on its own), and an input listener that could
    not tell the two apart would fire a save on every character typed while searching.

    Mutation: delete the `if (form) form.addEventListener("input", ...)` line from wire() (or
    drop the `e.target && e.target.name` guard) and this fails — either nothing arms, or the
    county box starts saving too."""
    t = ran["typing"]
    assert t["wired"], "wire() still has no input listener on the form"
    assert t["armedOnNamedField"] == 1, "typing into a named field did not arm the 600ms debounce"
    assert t["savedFromTyping"] == 1, "the armed save never actually reached TW.setState"
    assert t["quietOnCountyInput"] == 0, (
        "the county search box armed a save too — every keystroke while searching would save")


@needs_node
def test_leaving_the_page_flushes_a_pending_save_instead_of_losing_it(ran):
    """shared.js's own pagehide net (shared.js:513) only flushes a timer THIS page armed -- and
    before this fix, typing never armed one, so the net had nothing to catch. wire() now runs the
    save synchronously and forces the network PUT via TW.flushState() rather than trusting the
    600ms window to survive a tab close or step-nav click.

    Mutation: remove the pagehide handler (or its `if (!saveTimer) return;` guard so it fires a
    save from nothing) and this fails either way."""
    p = ran["pagehideFlush"]
    assert p["wired"], "polish-intake.js registers no pagehide handler at all"
    assert p["armedBeforeLeaving"] == 1, "typing did not arm a timer for pagehide to catch"
    assert p["savedSynchronously"] == 1, "pagehide did not push the pending save through"
    assert p["armedAfterLeaving"] == 0, "pagehide left the 600ms timer armed behind it"
    assert p["flushedTheNetwork"] == 1, "pagehide saved locally but never called TW.flushState()"
    assert p["quietWhenNothingArmed"], (
        "leaving with nothing typed must not manufacture a save or a flush out of thin air")


@needs_node
def test_a_refused_cross_tab_write_now_tells_the_estimator(ran):
    """shared.js silently refuses a write when another browser tab has re-stamped the shared
    localStorage blob onto a different draft — a console.warn only, invisible to an estimator, and
    a literal match for "switches to a different tab and it doesn't save." paintSaveBlocked()
    surfaces TW.saveBlocked() into its own #save-note element, deliberately separate from
    #sandbox-note (the test-copy identity banner set once at boot, which this must never
    overwrite).

    Mutation: make paintSaveBlocked a no-op, or have it write into #sandbox-note instead, and this
    fails."""
    s = ran["saveBlockedNote"]
    assert s["shownWhenBlocked"], "a refused save leaves no visible warning"
    assert s["textMentionsAnotherTab"], "the warning doesn't explain what happened"
    assert s["hiddenWhenNotBlocked"], "the warning stays shown even once a save actually lands"


# ── the sandbox settles first ────────────────────────────────────────────────
@needs_node
def test_nothing_renders_before_the_sandbox_has_settled(ran):
    """The whole point of the beta sandbox: this page opens on whatever project you came from and
    saves a toggle within a second of the first click, so it must not have a toggle to click until
    it knows which draft it may write to.

    Mutation: render the form first and enter the sandbox after. On screen it looks identical, and
    a fast click writes a condition onto a live customer bid."""
    b = ran["bootOrder"]
    assert not b["anyPaintBeforeSandbox"], (
        "the page rendered before the sandbox was even asked: %r" % b["log"])
    assert b["sandboxFirst"], "the first paint happens before the sandbox settles: %r" % b["log"]
    assert b["loadingHidden"] and b["mainShown"], "the form is never revealed at all"
    assert b["repointedAfterSandbox"], (
        "the step links are stamped with the draft id BEFORE the sandbox may have moved the page "
        "onto a test copy, so they would carry the real project's id")


@needs_node
def test_a_sandbox_that_could_not_settle_stops_the_page(ran):
    """enterSandbox returns false when it could not decide safely. Rendering the form anyway would
    offer an estimator a box to type a real customer's job into.

    Mutation: ignore the return value."""
    s = ran["bootOrder"]["stopped"]
    assert s["renders"] == [], "the page rendered after the sandbox refused: %r" % s["renders"]
    assert s["mainStillHidden"], "the form was revealed after the sandbox refused"
    assert s["noListeners"], "click handlers were wired even though the draft was never settled"
    assert s["formNeverRead"] and s["nothingSaved"] == 0


@needs_node
def test_the_page_renders_the_copy_the_sandbox_moved_it_onto(ran):
    """The sandbox can switch this page onto a test copy mid-boot. Rendering the copy with the real
    project's values still in the boxes is the same silent mix-up in the other direction.

    Mutation: hydrate from the blob read before enterSandbox ran."""
    c = ran["copyAdopted"]
    assert c["hydratedFrom"] == "Nearman Creek (beta test)", (
        "the form was filled from the project that was clicked, not the copy being edited")
    assert c["hydratedIntoTheForm"], "writeForm was handed something that is not the form"
    assert c["projLine"] == "Nearman Creek (beta test) · Bonner Springs, KS"
    assert c["rendered"][:4] == [
        ["local", False], ["prevailing_wage", False],
        ["taxable", True], ["remodel_tax", False]], (
        "the toggles show the source project's conditions, not the copy's")
    # And the cell-borne answers are re-read from the COPY's cell_values on the same pass —
    # adoptModel reassigns both bindings together, because a page that switched drafts mid-boot and
    # only re-read one of them would mix the copy's answers with the source project's.
    #
    # THE TWO HALVES NOW LAND IN DIFFERENT PLACES, which is why this reads the model as well as the
    # screen. Renovation comes back into the `carry` binding and shows as a switch. Joint filler
    # came off this form on 2026-09-16 and comes back onto M.conditions instead, where nothing on
    # this page renders it — so its half of the re-read is invisible here and has to be asserted
    # against the model, or the copy would quietly inherit the source project's joint filler and
    # write it into the copy's workbook.
    #
    # The copy says Reno and no joint filler; both are the opposite of the default, so this cannot
    # pass by accident.
    assert c["rendered"][4:] == [
        ["bond", False],
        ["reno", True]]
    assert c["modelConds"]["joint_filler"] is False, (
        "the model kept the source project's joint filler after the sandbox switched drafts — "
        "Polish!E29 on the COPY says No")
    # The engine four on the model came from the copy too, and the three moved ones that the copy
    # says nothing about fall back to freshModel's answers rather than to the source project's.
    assert c["modelConds"] == {
        "local": False, "prevailing_wage": False, "taxable": True,
        "remodel_tax": False, "bond": False,
        "dye": False, "joint_filler": False, "remove_existing_jf": False}
    assert json.loads(c["savedTakeoff"]) == [{"area": "Copy bay", "sf": 500}], (
        "a save after the switch wrote the wrong draft's takeoff")
    assert c["savedRemodel"] is True


@needs_node
def test_every_pill_link_carries_the_draft_the_page_settled_on(ran):
    """The REAL frontend/js/polish-sandbox.js, run over the anchors parsed out of this page, after
    shared.js's own rule (read out of shared.js, so the two cannot drift) has had its turn.

    Two halves, and both are load-bearing. shared.js stamps the three wizard pages with the id the
    page opened on and skips the beta pages entirely — _WIZARD_PATH does not list them. So "2 ·
    Estimate" leaves this page with NO ?d= unless the sandbox gives it one, and the other two leave
    it carrying the id the estimator arrived with, which on a test copy is the real project's."""
    p = ran["pills"]
    # NOT VACUOUS, and said out loud because for one afternoon it nearly was. Every list below is
    # derived from this page's markup, and the harness used to slice the pills out with a pair of
    # bare indexOf calls: when the step row's markup changed, both missed, `slice(-1, -1)` returned
    # "", `raw` came back empty, and the harness did not crash. `withNoDraft == stampedBySharedJs`
    # would then have been [] == [] and reported green. The harness now throws on a missed slice;
    # this is the same guard on the test's side of the boundary, so neither half can go quiet alone.
    assert all(p.values()), "the harness handed back an empty pill list: %r" % p
    assert p["raw"] == ["/polish-estimate.html", "/proposal-review.html", "/done.html"]
    assert p["stampedBySharedJs"][0] == "/polish-estimate.html", (
        "shared.js has started stamping the beta pages; if _WIZARD_PATH now covers them this test "
        "and the sandbox's BETA_PATH rule both want revisiting")
    assert p["afterSandbox"] == [
        "/polish-estimate.html?d=proj-1-beta",
        "/proposal-review.html?d=proj-1-beta",
        "/done.html?d=proj-1-beta"], (
        "a step link still points somewhere other than the draft this page settled on: %r"
        % p["afterSandbox"])
    assert p["withNoDraft"] == p["stampedBySharedJs"], (
        "with no draft id at all the links were rewritten anyway")


@needs_node
def test_the_bid_date_defaults_to_today_without_overwriting_one(ran):
    """Same default as the live intake, so nobody has to think about it — and a date already on the
    draft is left exactly as it is."""
    assert len(ran["bidDate"]["defaulted"]) == 10 and ran["bidDate"]["defaulted"][4] == "-", (
        "the bid date default is not an ISO yyyy-mm-dd value: %r" % ran["bidDate"]["defaulted"])
    assert ran["bidDate"]["keptWhatWasThere"] == "2026-12-24"


# ── the county, and the real remodel-tax rate ────────────────────────────────
#
# WHAT HANZ ASKED FOR, 2026-08-18: "For the Remodel tax please use the real state tax or city tax,
# DONT USE 10%."
#
# Kyle's workbook hardcodes the remodel tax at 10% (Polish!B75). That is not a real rate anywhere.
# Kansas charges sales tax on commercial remodel LABOR at the state rate plus the county portion
# only — 6.5% + 1.475% = 7.975% in Johnson County, less in most others — and the live estimating tool
# has looked it up per county since 2026-06-02. markupChain() now takes `remodel_rate` as an input,
# so the beta intake is where that rate comes from.
#
# ONE OPEN QUESTION, DELIBERATELY NOT DECIDED HERE. markupChain documents `null` ("nobody has said
# which county" → stand the Kansas state rate up) and an explicit `0` ("we know, and it is nothing":
# Missouri exempts remodel labor) as different inputs. js/polish-estimate.js hands it
# `B.num(state.county_remodel_rate)`, which flattens both to 0. The harness reports BOTH numbers —
# `enginePct.raw` and `enginePct.asWired` — so the divergence is visible instead of averaged away.
# The assertions below pin only what is not in question: a Kansas job is charged its county's real
# rate, and a Missouri job is not charged a Kansas one.
@needs_node
def test_the_county_list_comes_from_the_api_and_never_from_the_page(ran):
    """backend/reference_tax.py is the county table, pulled county-by-county out of the KS DOR
    Address Tax Rate Locator. A copy of it inside the page would be a second table to keep in step
    with the DOR — silently wrong the first time a county changes its portion.

    Executed rather than grepped: the page is asked to search BEFORE the fetch resolves, and again
    with reference data down. A hardcoded list would answer both."""
    assert ran["county"]["searchedBeforeTheListArrived"] == 0, (
        "the search box matched rows before /api/reference/counties had answered, so the county "
        "table is baked into the page")
    assert ran["countyHydrated"]["searchWithReferenceDataDown"] == 0, (
        "the search still returns rows with reference data down — there is a fallback table in "
        "the page")
    assert ran["county"]["fetched"], "the page never fetched the county list at all"
    for f in ran["county"]["fetched"]:
        assert f["url"] == "/api/reference/counties", (
            "the page fetched something other than the reference endpoint: %r" % f["url"])
        assert f["headers"] is not None, (
            "the fetch carries no headers, so it goes out without the bearer token and 401s")


@needs_node
def test_picking_a_kansas_county_writes_the_four_keys_the_live_screen_writes(ran):
    """THE CONTRACT. `county`, `county_tax_rate`, `county_remodel_rate`, `county_notes` are the live
    estimate screen's own keys, in its own "<Name> County, ST" shape, so a project that picked its
    county on either screen is understood by both — js/polish-estimate.js reads
    `county_remodel_rate` off the draft without caring which screen set it.

    The expected rate is read out of backend/reference_tax.py by the harness, not retyped here: a
    fixture with an invented rate would keep passing after the table it pins had changed.

    Mutation: write the rate under `remodel_rate`, or store the bare county name. The pick looks
    perfect on screen and the estimate page prices at the state fallback for ever."""
    keys = ran["county"]["keys"]
    table = ran["johnsonKs"]
    assert keys == {
        "county": "Johnson County, KS",
        "county_tax_rate": table["rate"],
        "county_remodel_rate": table["remodel_rate"],
        "county_notes": table["notes"],
    }, "the four draft keys are not the live screen's: %r" % keys
    assert keys["county_remodel_rate"] == 0.07975, (
        "Johnson County, KS is not charging the KS DOR's 7.975%")
    # Priced through the real engine, both the way its contract reads and the way the estimate page
    # calls it. A real rate survives either, which is why this is the case that must be exact.
    assert ran["county"]["enginePct"] == {"raw": 0.07975, "asWired": 0.07975}, (
        "the rate this page wrote does not reach the bid as 7.975%: %r"
        % ran["county"]["enginePct"])


@needs_node
def test_both_johnson_counties_are_offered_because_they_charge_different_rates(ran):
    """There is a Johnson County in Kansas and a Johnson County in Missouri, and they are not the
    same bid. The picker has to show both and say which is which.

    Mutation: match on name only and take the first hit — every Johnson County job in Overland Park
    gets priced as Warrensburg."""
    assert ran["county"]["offeredForJohnson"] == [
        ["Johnson County, MO", "remodel labor exempt"],
        ["Johnson County, KS", "remodel 7.975%"]], (
        "the two Johnsons are not both offered, with their rates: %r"
        % ran["county"]["offeredForJohnson"])
    assert ran["county"]["clicked"] == "Johnson County, KS", "the harness clicked the wrong row"


@needs_node
def test_choosing_a_county_does_not_delete_the_takeoff(ran):
    """THE MERGE, from the county's direction. A pick rides the same debounced save as everything
    else on this page, and that save PUTs the whole blob — including `polish_estimate`, where the
    calculator's finished takeoff and labor rows live.

    Mutation: write the four keys with a setState that drops polish_estimate, and choosing a county
    deletes a finished takeoff. Nobody finds out until the bid comes back at zero."""
    c = ran["county"]
    assert json.loads(c["takeoffKept"]) == [
        {"assembly_id": "asm-sp", "assembly_name": "Salt & Pepper polish",
         "measurement": 12500, "unit": "SF"},
        {"assembly_id": "asm-edge", "assembly_name": "Edge grind",
         "measurement": 900, "unit": "LF"}], "the takeoff did not survive picking a county"
    assert json.loads(c["laborKept"]) == [
        {"id": "polishing", "label": "Polishing", "guys": 4, "days": 3, "rate": 32.2},
        {"id": "mockup", "label": "Mock-up", "guys": 3, "days": 0.5, "rate": 32.2},
        # Backfilled by migrateModel() at boot — see the toggle test above.
        {"id": "travel", "label": "Travel", "guys": "", "days": "", "rate": 33,
         "unit": "hours", "guys_auto": True}], (
        "the labor rows did not survive picking a county")
    assert c["versionKept"] == 2, "the model's version was dropped by a county pick"
    # All EIGHT of the model's conditions, not just the five this form renders. Since 2026-09-16
    # the model also carries dye, joint_filler and remove_existing_jf, answered on the Takeoff
    # step — and a county pick is exactly the kind of unrelated save that would drop them if it
    # wrote the model from this page's own list instead of merging into what was there.
    assert c["conditionsKept"] == {
        "local": True, "prevailing_wage": False,
        "taxable": True, "remodel_tax": False, "bond": False,
        "dye": False, "joint_filler": False, "remove_existing_jf": False}, (
        "the job conditions did not survive picking a county")
    assert c["debounced"] and c["savedOnce"], (
        "a pick does not go through the page's own 600ms debounce, so it either writes on every "
        "keystroke or not at all")


@needs_node
def test_a_missouri_county_is_left_without_a_remodel_rate_and_says_why(ran):
    """Missouri rows carry no `remodel_rate`, and that is CORRECT rather than missing data: MO taxes
    the contractor on materials and leaves remodel labor exempt. So the key stays null instead of
    being filled in with a Kansas number, and the note says the rule out loud.

    Also the search that found it: "warrensburg" is a TOWN, matched out of the county's notes,
    because nobody writes the county on a drawing set.

    Mutation: fall back to the state rate when a row has no remodel_rate, and every Missouri bid
    quietly grows a Kansas tax."""
    mo = ran["countyMo"]
    assert mo["offered"] == [["Johnson County, MO", "remodel labor exempt"]], (
        "searching the notes for a town did not find its county: %r" % mo["offered"])
    assert mo["keys"]["county"] == "Johnson County, MO"
    assert mo["keys"]["county_remodel_rate"] is None, (
        "a Missouri county was given a remodel rate: %r" % mo["keys"]["county_remodel_rate"])
    for note in (mo["noteWithRemodelOff"], mo["noteWithRemodelOn"]):
        assert "generally exempt" in note, (
            "the note does not say Missouri remodel labor is generally exempt: %r" % note)
    assert "turn it off for a missouri job" in mo["noteWithRemodelOn"].lower(), (
        "with Remodel tax left on for a Missouri job the note gives no instruction: %r"
        % mo["noteWithRemodelOn"])
    # What the bid is actually charged today, priced through the real engine off the key this page
    # wrote. The number that must not appear here is the Kansas one.
    assert mo["enginePct"]["asWired"] == 0, (
        "a Missouri job is being charged a remodel rate of %r — see the note above this section "
        "about null vs 0; if polish-estimate.js starts handing markupChain the raw key, a Missouri "
        "county has to be written as 0 here rather than null" % mo["enginePct"]["asWired"])


@needs_node
def test_remodel_tax_with_no_county_names_the_kansas_state_rate(ran):
    """The engine stands the Kansas state rate up when the remodel toggle is on and nobody has said
    which county. The page has to name that rate, because the estimator is about to price a job on
    it — and the alternative they would otherwise assume is the workbook's 10%.

    Mutation: leave the field silent. The bid is 6.5% and every estimator who knows the sheet reads
    it as 10%."""
    fb = ran["countyFallback"]
    assert "6.5%" in fb["note"], (
        "the fallback note does not name the Kansas state rate: %r" % fb["note"])
    assert "no county" in fb["note"].lower(), (
        "the note does not say that no county has been picked: %r" % fb["note"])
    assert fb["keys"] == {"county": "", "county_tax_rate": None,
                          "county_remodel_rate": None, "county_notes": ""}, (
        "a county nobody picked was invented on the draft: %r" % fb["keys"])
    assert fb["field"]["clearShown"] is False, "there is a Clear button with nothing to clear"
    # The rate the note promises is the engine's own fallback, and the engine's constant is the same
    # 6.5% the server's reference table calls the Kansas state rate.
    from reference_tax import KS_STATE_RATE
    assert ran["ksStateRate"] == KS_STATE_RATE == 0.065, (
        "js/polish-bid-core.js and backend/reference_tax.py disagree about the Kansas state rate, "
        "so the note names a rate the bid does not use: %r vs %r"
        % (ran["ksStateRate"], KS_STATE_RATE))
    assert fb["enginePct"]["raw"] == KS_STATE_RATE, (
        "the engine does not fall back to the Kansas state rate for the keys this page wrote")


@needs_node
def test_the_note_says_when_the_county_is_not_affecting_the_price_yet(ran):
    """The county only moves money when Remodel tax is on. Saying so is what stops an estimator
    picking a county, seeing the total not budge, and assuming the field is broken.

    Mutation: print the rate and nothing else."""
    off = ran["county"]["field"]["note"]
    assert "7.975%" in off and "Johnson County, KS" in off, (
        "the note does not say which rate the picked county would use: %r" % off)
    assert "not affecting the price yet" in off, (
        "with Remodel tax off the note does not say the county is not affecting the price: %r" % off)
    on = ran["county"]["noteWithRemodelOn"]
    assert "7.975%" in on and "not affecting the price" not in on, (
        "with Remodel tax on the note still says the county is doing nothing: %r" % on)
    nothing = ran["countyFallback"]["noteWithRemodelOff"]
    assert "not affecting the price yet" in nothing, (
        "with no county and Remodel tax off the field says nothing useful at all: %r" % nothing)


@needs_node
def test_nothing_this_page_renders_offers_the_workbooks_ten_percent(ran):
    """Hanz, verbatim: "DONT USE 10%". Not as the rate, not as an option, not as a leftover of the
    sheet's own wording — this page is where an estimator decides what the remodel tax is, and 10%
    being visible anywhere on it is the instruction being ignored.

    Checked over everything the page painted in every scenario in the harness, not over the source:
    the string that matters is the one an estimator can read."""
    painted = ran["rendered"]
    assert painted, "the harness collected no rendered output, so this test is vacuous"
    offenders = [s for s in painted if "10%" in s]
    assert offenders == [], "the page rendered the workbook's 10%%: %r" % offenders
    # And the check is looking at real output: the rates that SHOULD be there are.
    joined = " ".join(painted)
    assert "7.975%" in joined, "no county rate was rendered anywhere — the sweep above is vacuous"
    assert "6.5%" in joined, "the Kansas state fallback was never rendered"


@needs_node
def test_the_county_is_hydrated_from_the_draft_on_load(ran):
    """A project that picked its county on the LIVE estimate screen has to show that county here.
    Otherwise the estimator picks one a second time, and the second pick is the one that counts.

    Read off the DRAFT, not out of the API: with reference data down the field still shows it, which
    is the difference between "reference data is unavailable" and "your county was lost".

    Mutation: hydrate from the county list by matching names, and the field is empty on every load
    until the fetch lands."""
    h = ran["countyHydrated"]
    assert h["field"]["input"] == "Wyandotte County, KS", (
        "the county on the draft is not in the field: %r" % h["field"]["input"])
    assert "7.5%" in h["field"]["note"], (
        "the hydrated county's rate is not on screen: %r" % h["field"]["note"])
    assert h["field"]["clearShown"] is True, "a hydrated county cannot be cleared"
    assert h["field"]["resultsHidden"] is True, "the search list is open before anybody typed"
    assert h["withReferenceDataDown"] == "Wyandotte County, KS", (
        "the field is empty when /api/reference/counties is down, so a project looks like it lost "
        "its county")
    # THE CLOBBER. Every save on this page PUTs the whole blob, so a county set on the other screen
    # has to be written back by a save this page makes for an entirely unrelated reason.
    assert h["keysAfterAnUnrelatedToggle"] == {
        "county": "Wyandotte County, KS", "county_tax_rate": 0.01,
        "county_remodel_rate": 0.075, "county_notes": "KCK, Bonner Springs."}, (
        "flipping an unrelated toggle wiped the county the live estimate screen had set: %r"
        % h["keysAfterAnUnrelatedToggle"])


@needs_node
def test_the_search_is_keyboard_usable_and_enter_never_leaves_the_page(ran):
    """The input lives INSIDE the form, and the form's submit handler navigates to the estimate. So
    Enter on a highlighted row has to be swallowed — otherwise choosing a county with the keyboard
    leaves the page instead, carrying whatever was there before.

    Mutation: drop the preventDefault. With a mouse it is perfect; with a keyboard it walks the
    estimator to step 2 mid-search."""
    k = ran["countyKeyboard"]
    assert k["openedOnTyping"], "typing does not open the list"
    assert k["highlightSteps"] == [0, 1, 0, 1, 1], (
        "the arrow keys do not walk the rendered rows: %r" % k["highlightSteps"])
    assert k["preventedDefaults"] == 5, (
        "an arrow or Enter reached the page unprevented — Enter submits the form and the arrows "
        "move the caret instead of the cursor")
    assert k["picked"] == "Johnson County, KS", (
        "Enter did not choose the highlighted row: %r" % k["picked"])
    assert k["savedOnce"] and k["closedAfterPick"] is True
    assert k["navigated"] == [], (
        "choosing a county with the keyboard navigated to %r" % k["navigated"])
    assert k["escapeClosed"] is True and k["escapeSaved"] == 0, (
        "Escape either leaves the list open or writes something")
    assert k["escapeRestoredTheField"] == "Johnson County, KS", (
        "an abandoned search left its typed text in a field whose draft says a different county — "
        "the field would be naming the wrong county: %r" % k["escapeRestoredTheField"])


@needs_node
def test_clear_puts_the_four_keys_back_the_way_a_project_with_no_county_has_them(ran):
    """A wrong county is a wrong price, so it has to be removable — and removing it has to write,
    not just blank the box.

    Mutation: clear the input and leave countyPick alone. The screen says no county and the bid is
    still priced on the old one."""
    c = ran["countyClear"]
    assert c["keys"] == {"county": "", "county_tax_rate": None,
                         "county_remodel_rate": None, "county_notes": ""}, (
        "Clear did not write the county away: %r" % c["keys"])
    assert c["field"]["input"] == "" and c["field"]["clearShown"] is False
    assert "not affecting the price yet" in c["field"]["note"], (
        "after Clear the note still describes a county: %r" % c["field"]["note"])


@needs_node
def test_the_list_closes_on_a_click_away_and_not_on_a_click_into_it(ran, html):
    """Clicking back into the box the estimator is typing in must not shut the list they are
    choosing from. Marked with an attribute rather than measured against the element, because a
    click lands on the row's inner span as often as on the row.

    The stand-in in the harness sets that attribute, so the page's own markup is pinned here — a
    fixture agreeing with itself would prove nothing."""
    assert 'id="county-input"' in html and "data-county-keep" in html, (
        "the county field carries no data-county-keep, so every click on it closes the list")
    field = html[html.index('id="county-field"'):html.index('id="county-note"')]
    assert field.count("data-county-keep") == 2, (
        "data-county-keep is not on both the input and the results box: %r" % field)
    o = ran["countyOutside"]
    assert o["openAfterClickingTheBox"], "clicking into the search box closes its own list"
    assert o["closedAfterClickingAway"] is True, "clicking elsewhere leaves the list open"
    assert o["inputAfterClickingAway"] == "", (
        "an abandoned search stayed in the box, where it reads as a chosen county: %r"
        % o["inputAfterClickingAway"])
    assert o["savedNothing"] == 0, "closing the list queued a save"


@needs_node
def test_the_offered_list_is_typed_down_rather_than_scrolled(ran):
    """Every row in the table matches "county". Offering all thirty-odd of them is a scroll, and the
    estimator knows the name — they type it."""
    assert ran["county"]["cappedRows"] == ran["county"]["cap"] == 12, (
        "the picker offered %r rows for a search that matches everything"
        % ran["county"]["cappedRows"])


# ── the static shell ─────────────────────────────────────────────────────────
# Legitimately source-level: these are facts about the page's <head> and <nav>, not behaviour.
def test_the_page_carries_no_inline_script(html):
    """The CSP refuses inline <script> and onclick=, and the refusal is silent — the page renders
    and then nothing works, which reads exactly like a logic bug."""
    for chunk in html.split("<script")[1:]:
        head, _, body = chunk.partition(">")
        if "src=" in head:
            continue
        assert not body.split("</script>")[0].strip(), "inline <script> block"
    assert "onclick=" not in html.lower()


def test_the_sandbox_loads_before_the_page_script(html):
    """polish-intake.js reads window.TWPolishSandbox as it runs. Loaded the other way round it is
    undefined, boot() throws on its first line, and the page renders a loading message for ever.

    Mutation: swap the two tags."""
    assert "/js/polish-sandbox.js" in html, "the page never loads the sandbox at all"
    assert html.index("/shared.js") < html.index("/js/polish-sandbox.js"), (
        "the sandbox module reads TW.* as it runs")
    assert html.index("/js/polish-sandbox.js") < html.index("/js/polish-intake.js")


def test_the_page_loads_no_formula_engine(html):
    """It writes eight text boxes and five toggles onto a draft. HyperFormula is a megabyte off a
    CDN plus a whole workbook load, and it belongs to the calculator.

    Read past the comments, which say the same thing in words."""
    markup = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert "hyperformula" not in markup.lower(), "the beta intake form loads a formula engine"
    assert "xl-core.js" not in markup, "the beta intake form loads the workbook helpers"
    srcs = re.findall(r'<script[^>]*src="([^"]+)"', markup)
    # polish-verbal.js joined the list on 2026-08-25 — the verbal intake panel. It is browser
    # dictation (Web Speech API, no library) plus one fetch, and it loads AFTER polish-intake.js
    # because it calls window.TWPolishIntake.applyVerbal, which that file publishes as it boots.
    # The order is asserted, not just the membership: swapped, the panel would find no hook and
    # silently fill nothing.
    # /js/icons.js is FIRST, ahead of auth.js: the sidebar auth.js draws asks it for every glyph
    # in the rail. See the house rule at the top of frontend/js/icons.js.
    assert srcs == ["https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.0",
                    "/js/icons.js", "/auth.js", "/shared.js", "/js/polish-bid-core.js",
                    "/js/polish-sandbox.js", "/js/polish-intake.js",
                    "/js/polish-verbal.js"], (
        "the page's script list has changed: %r" % srcs)
    # polish-bid-core is the model's shape and the condition keys, NOT a formula engine: no CDN, no
    # workbook fetch. It is here because this page writes the model the calculator prices, and the
    # version it stamps is what routes a resumed project back to this intake.
    assert html.index("/js/polish-bid-core.js") < html.index("/js/polish-intake.js"), (
        "`var B = window.TWPolishBid` runs at parse time")


def test_the_step_row_says_where_you_are_and_where_the_beta_goes(html):
    """Four pills, Intake current, and step 2 pointing at the BETA calculator rather than the
    spreadsheet screen — which is the confusion Hanz reported on 2026-08-11 ("it leads me to the
    excel sheet still").

    Re-expressed on 2026-09-10 against the live intake's shared `.progress` / `.step.active` shell,
    which this page adopted in place of its own `<nav class="steps">` / `<span class="on">`. Every
    claim above is unchanged; only the class names the shell uses are. The pills MUST carry
    `.progress` specifically: auth.js finds them by `pageHeader.querySelector(".progress")` and
    folds them into its one-line header, and a renamed container would silently leave them behind
    in a `header.topbar` whose children it then replaces."""
    nav = html[html.index('<div class="progress">'):html.index("</header>")]
    assert '<span class="step active">1 · Intake</span>' in nav, (
        "the Intake pill is not the current page")
    assert 'href="/polish-estimate.html">2 · Estimate' in nav, (
        "step 2 does not point at the beta calculator")
    assert 'href="/proposal-review.html">3 · Proposal' in nav
    assert 'href="/done.html">4 · Files' in nav
    assert nav.count("<a ") == 3, "an unexpected number of links in the step row"


def test_the_page_says_it_is_the_beta_and_a_separate_form(html):
    """Two intake forms is a surprise unless the page says so. Hanz: "Intake form of Beta and
    Active projects should be separate for now, since this is for testing.\""""
    assert '<span class="beta">BETA</span>' in html, "there is no BETA badge"
    assert "separate from the live intake" in html, (
        "the page never says it is separate from the live intake form")


def test_there_is_somewhere_for_the_sandbox_notice_to_render(html):
    """showCopyNote/showDirectNote are null-guarded, so a missing container is not a crash — it is
    a page that quietly stops telling the estimator it moved them onto a test copy."""
    assert 'id="sandbox-note"' in html
    assert 'id="loading"' in html, (
        "enterSandbox reports a stop it cannot recover from into #loading; without one, the page "
        "would sit on a blank screen with no explanation")


# ── the seam with the calculator ──────────────────────────────────────────────
# These two are the only tests that span both beta pages, and they exist because the seam was
# genuinely broken: on a brand-new project this page wrote `polish_estimate: {conditions: …}` with
# no version, and BOTH readers of that blob mishandled it without saying anything.
@needs_node
def test_a_brand_new_project_is_saved_as_a_model_the_calculator_can_read(ran):
    """The round trip, executed: what this page saved, read back through the real
    polish-bid-core.js that the calculator prices with.

    THE BUG: a version-less blob fell through migrateModel's v2 and v1 branches to `return fresh`,
    so the estimator set prevailing wage and taxable here, clicked Continue, and the calculator
    priced the job at standard rates with sales tax on — while this screen still showed both
    switches the way they had left them. Nothing on either page said a word.

    Mutation: drop the `B.migrateModel(existing)` call in save() back to `Object.assign({}, existing)`
    and these conditions come back as the defaults."""
    seam = ran["seam"]
    assert seam["savedVersion"] == 2, (
        "the beta intake saved a model with no version stamp; the calculator reads that as "
        "unrecognised and replaces the estimator's conditions with defaults")
    assert seam["savedConditions"]["prevailing_wage"] is True
    assert seam["savedConditions"]["taxable"] is False
    assert seam["readBackConditions"] == seam["savedConditions"], (
        "the calculator did not read back the conditions this page saved: %r vs %r"
        % (seam["readBackConditions"], seam["savedConditions"]))


@needs_node
def test_a_brand_new_project_is_flagged_for_the_beta_intake_on_resume(ran):
    """backend/drafts.py._polish_beta() decides which intake a project reopens on by reading
    `data.polish_estimate.version`, which PostgREST hands back as TEXT.

    Without the version stamp a project CREATED in the beta reopened on the live spreadsheet
    intake — the exact complaint that started this work, in the other direction."""
    from drafts import _polish_beta
    assert _polish_beta(ran["seam"]["routingFlagSees"]) is True, (
        "a project created in the beta intake would resume on the live intake"
    )


@needs_node
def test_this_page_does_not_state_labor_it_has_no_screen_for(ran):
    """THE THIRD SEAM BUG, and the same shape as the two above it: this page writing something it
    has no business writing, and the calculator reading it.

    save() says out loud that only `conditions` is this page's to state -- there is no labor UI
    here at all. It stated labor anyway until 2026-09-17, by accident: `B.migrateModel(existing)`
    fills a missing `labor` in from freshModel() before handing the model back, so the very first
    save on a brand-new project persisted four crew rows nobody had been shown.

    Harmless on its own. Not harmless in the seam: js/polish-estimate.js adds the library's
    default labor lines to a bid whose labor has never been stated (B.laborUnstated), and a model
    minted here had already stated it -- so "+ Add a labor line" on Library -> Default Items &
    Assemblies could never reach a project that started where every beta project starts.

    ABSENT, NOT EMPTY, and asked of the real core rather than restated here: `calculatorWouldSeed`
    is B.laborUnstated run on what this page actually saved, which is the same call the calculator
    makes. Checked after a SECOND save too, because this page saves on every keystroke and the
    guard reads what is already saved.

    Mutation: drop the `if (B.laborUnstated(cur.polish_estimate)) delete model.labor;` line.
    `mintedHasLaborKey` goes true and `calculatorWouldSeed` goes false."""
    ln = ran["laborNotStated"]
    assert ln["mintedHasLaborKey"] is False, (
        "the beta intake stated labor rows for a project whose estimator has never seen a labor "
        "screen, which disqualifies it from its own defaults")
    assert ln["secondSaveHasLaborKey"] is False, "the second save put the labor rows back"
    assert ln["calculatorWouldSeed"] is True and ln["calculatorWouldSeedAfterTwoSaves"] is True, (
        "the calculator will not seed the library's defaults onto a project this page minted")
    # Everything this page IS responsible for still lands. Dropping the key must not turn into
    # dropping the model: without the version stamp the project reopens on the live spreadsheet
    # intake (see the two seam tests above), and without conditions it prices at defaults.
    assert ln["mintedVersion"] == 2 and ln["mintedStillHasConditions"] and ln["mintedHasTakeoff"]
    # NOTHING IS LOST ON SCREEN. The calculator fills the display copy in from freshModel(),
    # which is exactly what it did with the rows this page used to persist -- the three crew rows
    # off Kyle's Polish tab at $33, and Travel.
    assert [r[0] for r in ran["laborNotStated"]["readBackLabor"]] == \
        ["polishing", "mockup", "jointfill", "travel"], (
            "the calculator no longer reads back the built-in rows: %r" % ln["readBackLabor"])
    assert [r[2] for r in ln["readBackLabor"]] == [33, 33, 33, 33]


@needs_node
def test_a_bid_that_has_been_worked_on_keeps_its_labor_through_a_toggle(ran):
    """The guard's other direction, and the expensive one. The moment the calculator writes a real
    labor array -- an estimator's crew numbers, and any default line they kept and re-rated --
    flipping a switch on this page must leave it strictly alone. `takeoff` and `labor` live under
    the same key as `conditions`, which is why save() merges rather than replaces; a blanket
    `delete model.labor` would be that same regression wearing a new hat.

    Mutation: drop the `B.laborUnstated(...)` guard and delete unconditionally. The estimator
    comes back from setting prevailing wage to find their crew rows reset to the seed."""
    ln = ran["laborNotStated"]
    assert ln["keptHasLaborKey"] is True, (
        "flipping a toggle deleted the labor rows off a bid that had been priced")
    saved = ln["keptLabor"]
    assert [r["id"] for r in saved][:2] == ["polishing", "lab-densify"], (
        "the saved labor rows came back changed: %r" % saved)
    assert saved[0]["guys"] == 4 and saved[0]["days"] == 6, (
        "an estimator's crew numbers were reset to the seed: %r" % saved[0])
    assert saved[1]["rate"] == 55, (
        "a kept default was written back to the library's own rate: %r" % saved[1])
    assert ln["keptCalculatorWouldSeed"] is False, (
        "a worked-on bid reads as seedable, so opening it would append the defaults again")
    # The toggle that was actually clicked still landed.
    assert ln["keptTaxable"] is False


# ── the Takeoff conditions' company answers are minted here ───────────────────
@needs_node
def test_a_brand_new_project_is_minted_with_the_librarys_condition_answers(ran):
    """WHY THIS PAGE SEEDS CONDITIONS IT NO LONGER DRAWS, and it is the seam rather than the form.

    The three Takeoff conditions moved off this screen on 2026-09-16 and it shows none of them.
    But THIS PAGE MINTS THE MODEL: a brand-new project has no polish_estimate, and the first save
    here writes a well-formed v2 through migrateModel, which fills all nine conditions in from
    freshModel. By the time polish-estimate.html opens they are STATED, and its own gate
    (conditionsUnstated) correctly refuses to touch them. Seed only there and the Library page's
    Defaults tab reaches nothing but a project that skipped intake -- which is not the normal flow
    and is barely any flow at all. This is the same shape of gap as the labor one above, from the
    other end.

    EVERY STORED ANSWER DISAGREES WITH WHAT THE TOOL SHIPS -- joint filler ships ON and the
    library says off -- so a seeder that was never wired up fails here rather than passing.

    Mutation: delete the `B.conditionsUnstated(...)` block from boot(). The minted model carries
    freshModel's literals, the estimate page then reads them as stated, and nothing an admin sets
    ever reaches a bid."""
    c = ran["conditionDefaults"]
    assert c["fetched"], "a brand new project never asked for the stored answers"
    assert c["minted"]["joint_filler"] is True, (
        "the library's 'on' did not reach the model this page mints, so the Defaults tab is "
        "unreachable from the normal flow. All three ship OFF since 2026-09-19, so the fixture "
        "sets all three ON -- one that agreed with freshModel would prove nothing")
    assert c["minted"]["dye"] is True
    assert c["minted"]["remove_existing_jf"] is True
    # AND THE CELLS AGREE ON THE SAME SAVE. Both screens read these back with the CELL winning,
    # so a seeded answer the cells did not carry would be reverted on the very next load.
    # All three "Yes": the fixture's library rows set all three ON, and all three SHIP off since
    # 2026-09-19, so each literal here can only have come from the seed.
    assert c["mintedCells"] == {"Polish!E29": "Yes", "Polish!E25": "Yes", "Polish!F29": "Yes"}, (
        "the seeded answers did not reach Kyle's workbook cells: %r" % c["mintedCells"])


@needs_node
def test_a_project_that_has_been_worked_on_keeps_its_own_conditions(ran):
    """THE HARD CONSTRAINT, on the page that mints the model. Hanz, verbatim: changing a default
    must not change any estimate that already exists.

    THE GATE IS OBSERVABLE, not inferred: a project that already has a polish_estimate never even
    asks for the defaults.

    Mutation: seed unconditionally in boot(). Flipping any switch on a worked project then writes
    today's defaults over the three answers somebody already gave, and conditionCellWrites puts
    them into Polish!E25/E29/F29 on the same save."""
    c = ran["conditionDefaults"]
    assert c["keptFetched"] is False, (
        "a project with a saved estimate asked for the condition defaults")
    assert c["kept"]["joint_filler"] is False, (
        "a saved 'off' was replaced by the library's 'on'")
    assert c["kept"]["dye"] is False
    assert c["kept"]["remove_existing_jf"] is False
    # …and the switch that was actually pressed did move, or this would pass against a save that
    # never happened.
    assert c["kept"]["taxable"] is False


@needs_node
def test_an_answer_already_in_a_cell_beats_the_library(ran):
    """THE CELL WINS WHERE THERE IS ONE, which is the rule both screens already follow and the
    reason conditionsFromCells runs OUTSIDE the seed rather than before it.

    A project that reached this page from the live intake has no polish_estimate at all -- exactly
    the blob conditionsUnstated calls seedable -- while an answer the AI autofill or an earlier
    visit gave sits in cell_values. Seeding last would overwrite it and the next save would make
    that permanent.

    ALL THREE CELLS ANSWERED, not one -- exactly what a real step-1 save on the live intake screen
    leaves behind (Polish!E29=Yes, Polish!E25=No, Polish!F29=No), and the library's stored default
    is the OPPOSITE of every one of them. A fixture that answered only one of the three could pass
    against a page that seeded the other two from the library regardless of what their cells said.

    Mutation: swap the two calls so seedConditionDefaults runs outermost. All three come back
    flipped and every cell answer already given is gone."""
    # THE FIXTURE IS TWO SHAPES, because one shape cannot prove both halves now that all three
    # ship OFF. joint_filler and dye have a library row saying ON against a cell saying "No", so
    # `False` here can only mean the cell beat the library. remove_existing_jf has NO library row
    # and a cell saying "Yes", so `True` there can only have come from the cell being read at
    # all -- which the first pair cannot show, because `False` is also what a page that read
    # neither would produce.
    c = ran["conditionDefaults"]["celled"]
    assert c["fetched"], "the library was never asked for its stored answers"
    assert c["dye"] is False, "the library's 'on' was written over the 'No' in Polish!E25"
    assert c["jointFiller"] is False, (
        "the library's 'on' was written over the 'No' in Polish!E29")
    assert c["removeExistingJf"] is True, (
        "the 'Yes' in Polish!F29 never reached the model, so the cells are not being read")


@needs_node
def test_the_defaults_table_being_absent_mints_the_model_anyway(ran):
    """`condition_defaults` is applied to NEITHER database as of 2026-09-18. A project that could
    not be created because a table nobody has promoted is missing would be a far worse outcome
    than one created with the answers the tool ships.

    Mutation: let the exception out of loadConditionDefaults. boot() then throws before hydrate(),
    and the intake form never appears on production."""
    d = ran["conditionDefaults"]["down"]
    for key in ("joint_filler", "dye", "remove_existing_jf"):
        assert d["conditions"][key] == d["shipped"][key], (
            "%s did not fall back to what the tool ships" % key)
