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
    assert srcs == ["https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.0",
                    "/auth.js", "/shared.js", "/js/polish-bid-core.js",
                    "/js/polish-sandbox.js", "/js/polish-intake.js"], (
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
