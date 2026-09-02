"""The BETA polish intake form, executed out of the real frontend/js/polish-intake.js.

WHAT HANZ ASKED FOR.

2026-08-17, on the beta calculator dropping from seven sub-steps to three: "The conditions we move
them to the intake form (For Beta Only). Intake form of Beta and Active projects should be separate
for now, since this is for testing." And, on the toggles themselves: "Keep them as toggle buttons."

So there are two intake forms. This one is small on purpose — a test harness for the beta polish
calculator, not a second copy of index.html — and it owns the five job conditions that used to be
the calculator's step 2.

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
by key to decide the hard-bid discount, the labour escalation and the two taxes. A key that drifted
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


# ── the five toggles ─────────────────────────────────────────────────────────
@needs_node
def test_all_five_conditions_render_as_toggles(ran):
    """Five switches, in the order the calculator showed them, each still a toggle.

    Mutation: render them as checkboxes, or lose one. Hanz asked for toggle buttons by name, and a
    condition that is not on screen is a condition nobody sets — it just silently keeps whatever
    the last project left behind."""
    keys = [s["key"] for s in ran["conditions"]["rendered"]]
    assert keys == ["local", "hard_bid", "prevailing_wage", "taxable", "remodel_tax"]
    assert [s["label"] for s in ran["conditions"]["rendered"]] == [
        "Local job", "Hard bid", "Prevailing wage", "Taxable", "Remodel tax"]
    assert ran["conditions"]["allAreSwitches"], "a condition rendered without its toggle track"
    assert ran["conditions"]["allHaveWhy"], (
        "a toggle lost its plain-English line — 'Hard bid' on its own tells an estimator nothing "
        "about what it does to the price")


@needs_node
def test_the_keys_are_the_ones_the_pricing_engine_reads(ran):
    """markupChain() in polish-bid-core.js looks each condition up BY KEY and a miss reads as
    `false`. Two lists, one contract — pinned against the real module so they cannot drift.

    Mutation: rename `remodel_tax` to `remodel` here. The toggle still works, still saves, still
    reads back — and the remodel tax silently never reaches the bid."""
    assert ran["conditions"]["pageKeys"] == ran["coreKeys"]


@needs_node
def test_the_documented_defaults_are_what_a_new_project_shows(ran):
    """Most jobs are local and taxable; the other three are the exceptions somebody has to know
    about. A brand-new project has no model at all, so these have to come from this page.

    Mutation: default everything to false, and every beta bid quietly loses its sales tax."""
    assert ran["conditions"]["defaults"] == {
        "local": True, "hard_bid": False, "prevailing_wage": False,
        "taxable": True, "remodel_tax": False}
    assert ran["conditions"]["freshRender"] == [
        ["local", True], ["hard_bid", False], ["prevailing_wage", False],
        ["taxable", True], ["remodel_tax", False]]


@needs_node
def test_a_v1_model_still_has_its_conditions_read(ran):
    """A draft priced before the rework carries {areas: […]} with no `version`, and its conditions
    in the same shape. Defaults fill only what it does not state.

    Mutation: read conditions only when `version` is set, and every older beta project silently
    reverts to local + taxable — including the prevailing-wage ones."""
    assert ran["conditions"]["v1Render"] == [
        ["local", False], ["hard_bid", False], ["prevailing_wage", True],
        ["taxable", True], ["remodel_tax", False]]


@needs_node
def test_the_spreadsheet_cell_chips_are_gone(ran):
    """B4/B5/D5/B6/D6 were on the calculator's panel, where Kyle could check a field against the
    workbook. This page writes the draft, not the workbook, so a cell name here points at
    something it never touches."""
    assert ran["conditions"]["noCellChips"], "a toggle still names a worksheet cell"


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
        {"id": "mockup", "label": "Mock-up", "guys": 3, "days": 0.5, "rate": 32.2}], (
        "the labor rows did not survive flipping a toggle")
    assert t["versionKept"] == 2, "the model's version was dropped by an intake save"
    # And the four conditions nobody touched are still what they were.
    assert t["siblingConditions"] == [
        ["local", True], ["hard_bid", False], ["taxable", True], ["remodel_tax", False]]


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
        {"id": "mockup", "label": "Mock-up", "guys": 3, "days": 0.5, "rate": 32.2}]
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
    assert c["rendered"] == [
        ["local", False], ["hard_bid", True], ["prevailing_wage", False],
        ["taxable", True], ["remodel_tax", False]], (
        "the toggles show the source project's conditions, not the copy's")
    assert json.loads(c["savedTakeoff"]) == [{"area": "Copy bay", "sf": 500}], (
        "a save after the switch wrote the wrong draft's takeoff")
    assert c["savedRemodel"] is True and c["savedHardBid"] is True


@needs_node
def test_every_pill_link_carries_the_draft_the_page_settled_on(ran):
    """The REAL frontend/js/polish-sandbox.js, run over the anchors parsed out of this page, after
    shared.js's own rule (read out of shared.js, so the two cannot drift) has had its turn.

    Two halves, and both are load-bearing. shared.js stamps the three wizard pages with the id the
    page opened on and skips the beta pages entirely — _WIZARD_PATH does not list them. So "2 ·
    Estimate" leaves this page with NO ?d= unless the sandbox gives it one, and the other two leave
    it carrying the id the estimator arrived with, which on a test copy is the real project's."""
    p = ran["pills"]
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
# Kansas charges sales tax on commercial remodel LABOUR at the state rate plus the county portion
# only — 6.5% + 1.475% = 7.975% in Johnson County, less in most others — and the live estimating tool
# has looked it up per county since 2026-06-02. markupChain() now takes `remodel_rate` as an input,
# so the beta intake is where that rate comes from.
#
# ONE OPEN QUESTION, DELIBERATELY NOT DECIDED HERE. markupChain documents `null` ("nobody has said
# which county" → stand the Kansas state rate up) and an explicit `0` ("we know, and it is nothing":
# Missouri exempts remodel labour) as different inputs. js/polish-estimate.js hands it
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
        ["Johnson County, MO", "remodel labour exempt"],
        ["Johnson County, KS", "remodel 7.975%"]], (
        "the two Johnsons are not both offered, with their rates: %r"
        % ran["county"]["offeredForJohnson"])
    assert ran["county"]["clicked"] == "Johnson County, KS", "the harness clicked the wrong row"


@needs_node
def test_choosing_a_county_does_not_delete_the_takeoff(ran):
    """THE MERGE, from the county's direction. A pick rides the same debounced save as everything
    else on this page, and that save PUTs the whole blob — including `polish_estimate`, where the
    calculator's finished takeoff and labour rows live.

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
        {"id": "mockup", "label": "Mock-up", "guys": 3, "days": 0.5, "rate": 32.2}], (
        "the labour rows did not survive picking a county")
    assert c["versionKept"] == 2, "the model's version was dropped by a county pick"
    assert c["conditionsKept"] == {
        "local": True, "hard_bid": False, "prevailing_wage": False,
        "taxable": True, "remodel_tax": False}, (
        "the five job conditions did not survive picking a county")
    assert c["debounced"] and c["savedOnce"], (
        "a pick does not go through the page's own 600ms debounce, so it either writes on every "
        "keystroke or not at all")


@needs_node
def test_a_missouri_county_is_left_without_a_remodel_rate_and_says_why(ran):
    """Missouri rows carry no `remodel_rate`, and that is CORRECT rather than missing data: MO taxes
    the contractor on materials and leaves remodel labour exempt. So the key stays null instead of
    being filled in with a Kansas number, and the note says the rule out loud.

    Also the search that found it: "warrensburg" is a TOWN, matched out of the county's notes,
    because nobody writes the county on a drawing set.

    Mutation: fall back to the state rate when a row has no remodel_rate, and every Missouri bid
    quietly grows a Kansas tax."""
    mo = ran["countyMo"]
    assert mo["offered"] == [["Johnson County, MO", "remodel labour exempt"]], (
        "searching the notes for a town did not find its county: %r" % mo["offered"])
    assert mo["keys"]["county"] == "Johnson County, MO"
    assert mo["keys"]["county_remodel_rate"] is None, (
        "a Missouri county was given a remodel rate: %r" % mo["keys"]["county_remodel_rate"])
    for note in (mo["noteWithRemodelOff"], mo["noteWithRemodelOn"]):
        assert "generally exempt" in note, (
            "the note does not say Missouri remodel labour is generally exempt: %r" % note)
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
    assert srcs == ["https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.0",
                    "/auth.js", "/shared.js", "/js/polish-bid-core.js",
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
    excel sheet still")."""
    nav = html[html.index('<nav class="steps">'):html.index("</nav>")]
    assert '<span class="on">1 · Intake</span>' in nav, "the Intake pill is not the current page"
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
