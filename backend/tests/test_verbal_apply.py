"""applyVerbal — putting an accepted extraction onto the estimator's screen.

backend/tests/test_verbal_intake.py owns the SERVER half: which flags are allowed through at all,
and why a price flag needs a verbatim quote. This file owns what happens after they are allowed
through, and there are four ways that goes wrong, all of them silent:

  * **A switch that was already right gets flipped.** `toggleCondition` is a toggle, not a setter.
    The obvious loop — for every condition the server accepted, call toggleCondition — turns a
    correct form wrong. Nothing on screen says so; the only evidence is a price that moved.
  * **The boxes fill and nothing is saved.** There is no `input` listener anywhere in
    frontend/js/polish-intake.js — `wire()` binds a delegated click, a form submit and the county
    box, and that is the whole list. So dispatching an input event persists nothing, and applyVerbal
    has to call `saveSoon()` itself. THIS WAS THE LIVE BUG, and the reason it read as intermittent
    rather than broken: the fields survived only when a condition happened to flip in the same run
    and its save swept them up.
  * **The second run undoes a correction the estimator made by hand.** Three AI runs per five
    minutes means the normal shape of this feature is read, fix one thing, re-read. A re-read that
    puts the mistake back is worse than no re-read: the estimator watched themselves fix it.
  * **The caption over the form goes stale.** `#proj-line` names the project and the town, both of
    which are boxes this fills, and until now only `hydrate()` ever wrote it.

RUN, NOT READ. Every one of those lives in the relationship between applyVerbal, toggleCondition
and the model — a source-text assertion sees a loop and a correctly-named call and passes. The
harness lifts the real functions and executes them against the smallest form they touch, so "already
right" is observable as a save that did not happen.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "verbal-apply-harness.js"

# Where the carried four start on a project whose cells are blank: hydrate() falls back to each
# spec's `def`, and Joint filler ships ON -- one kit per 3,500 sq ft is how the sheet is built.
# Named here because "it did not move" and "it moved to false" are the same assertion against
# an empty dict, and telling those apart is the whole point of the two tests that use it.
CARRY_BASE = {"reno": False, "dye": False, "joint_filler": True, "remove_existing_jf": False}

BASE = {"local": True, "hard_bid": False, "prevailing_wage": False,
        "taxable": True, "remodel_tax": False}


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_a_flag_that_differs_is_set_and_saved(ran):
    """The straightforward half. The switch moves, the county note is repainted because it quotes
    the remodel toggle by name, and the draft is scheduled to save — all three because the change
    went through toggleCondition rather than round it."""
    g = ran["flips"]
    assert g["applied"] == {"filled": [], "applied": ["prevailing_wage"], "respected": []}
    assert g["conditionsAfter"]["prevailing_wage"] is True
    assert g["saves"] == 1, "the change was never scheduled to save"
    assert g["countyNoteRepaints"] == 1, (
        "the county note still quotes the old state of the switches")


def test_a_flag_that_is_already_right_is_left_alone(ran):
    """`toggleCondition` flips; it does not set. An extraction that agrees with the form — which is
    the common case, since `local` and `taxable` both default on and most jobs are both — would,
    under the obvious loop, turn them both OFF. The estimator watches the panel report "Local job
    on, Taxable on" and the switches read the opposite, having been correct before they asked.

    Asserted through the SAVE COUNT as well as the values: zero saves is the proof that nothing
    was written and then written back, rather than flipped twice by luck."""
    g = ran["alreadyRight"]
    assert g["conditionsAfter"]["local"] is True, "a correct switch was toggled off"
    assert g["conditionsAfter"]["taxable"] is True, "a correct switch was toggled off"
    assert g["saves"] == 0, "it saved a change it did not need to make"
    assert g["applied"]["applied"] == ["local", "taxable"], (
        "the panel must still report these as set — the estimator asked about them and the answer "
        "is that the form already agrees")


def test_filling_the_fields_schedules_exactly_one_save(ran):
    """THE BUG THIS FILE NOW EXISTS FOR.

    The panel printed "Filled in: Project name, City, Bid date" over eight boxes that never reached
    the draft. Nothing on the page listens for `input`, so the event the fill dispatches reaches
    nobody; `saveSoon()` is only called by toggleCondition, pickCounty, clearCounty and — from
    today — applyVerbal. That is also why it looked intermittent: an extraction that also flipped a
    condition got its fields saved by accident, on that toggle's save.

    ONE save, not one per field. Eight PUTs of the whole draft blob for one dictation is how two
    tabs clobber each other."""
    g = ran["fields"]
    assert g["inputValues"] == {"project_name": "Blue Valley West", "city": "Overland Park",
                                "bid_date": "2026-09-03"}
    assert g["applied"]["filled"] == ["project_name", "city", "bid_date"]
    assert g["saves"] == 1, (
        "the fields the panel says it filled in were not scheduled to save: %r" % g["saves"])


def test_the_fill_still_looks_like_a_keystroke(ran):
    """The input event stays even though nothing listens for it today. A programmatic fill should be
    indistinguishable from typing to anything that DOES listen later, and it has to bubble, because
    every handler this page has is delegated rather than bound per input.

    It is documented as a courtesy, not as the save. A comment claiming this event persisted the
    draft is how the bug above survived a review."""
    g = ran["fields"]
    assert [e["type"] for e in g["events"]] == ["input", "input", "input"]
    assert all(e["bubbles"] for e in g["events"]), (
        "the input events do not bubble, so a delegated handler would never see them")


def test_the_caption_over_the_form_follows_the_boxes(ran):
    """`#proj-line` is the "which project is this" line above the form, and it names two of the
    fields a dictation fills. Written only by hydrate() until now, so a verbal fill left the heading
    reading "Untitled project" directly above a form with the project's name in it."""
    g = ran["caption"]
    assert g["caption"] == "Blue Valley West · Overland Park, KS"
    assert g["captionWrites"] == ["Blue Valley West · Overland Park, KS"], (
        "the caption was repainted %d times for one fill" % len(g["captionWrites"]))
    # A town with no state is not "Overland Park, " — the same rule hydrate has always applied.
    assert ran["captionNoState"]["caption"] == "Blue Valley West"


def test_the_caption_reads_the_boxes_first_and_the_draft_second(ran):
    """A dictation that gave the town but not the job name must not blank the name the draft already
    carried, and must not keep the town the draft carried over the one just spoken. Boxes win where
    there is a box; the blob fills the rest."""
    g = ran["captionFromBlob"]
    assert g["caption"] == "Nearman Creek · Bonner Springs, KS"


def test_a_condition_nobody_wired_up_sets_nothing(ran):
    """`isCondition` is the gate, and it is the same one the switches themselves are built from.
    A county key is included in the fixture deliberately: the server strips those, and if that ever
    regressed this is the second place it would have to get past."""
    g = ran["unknownCondition"]
    assert g["applied"]["applied"] == []
    assert g["conditionsAfter"] == BASE
    assert g["saves"] == 0


def test_a_carried_through_flag_from_the_ai_reaches_its_switch(ran):
    """THE PAGE NOW AGREES WITH ITSELF ABOUT WHAT A CONDITION IS.

    The polish page renders nine switches: the engine five that move money, and four carried
    through from the live intake so both screens agree — Renovation, Dye, Joint filler, Remove
    existing joint filler. `toggleCondition` has taken a carried key since those nine shipped,
    and `applyVerbal` was still gating on `isCondition` alone — the engine five. Two halves of
    one page disagreeing about the same list.

    THE COMPARISON MOVED IN THE SAME EDIT, AND HAD TO. applyVerbal calls toggleCondition only
    when the flag DIFFERS, and it used to test that with `!!M.conditions[key]`. A carried key is
    never on the model — `migrateModel` whitelists condition keys against
    `freshModel().conditions` — so that read `undefined` for all four, and every carried flag
    looked like a change from off. The `joint_filler: false` below is what catches it: Joint
    filler ships ON, `!!undefined !== false` is false, so the old read would call it handled and
    leave the switch on while the panel said it had set it. `condOn(key)` knows which of the two
    bindings a key lives in, and for the engine five it returns exactly `!!M.conditions[key]`.

    NOT REACHABLE FROM DICTATION YET, AND GREEN HERE DOES NOT SAY OTHERWISE. `verbal_intake.py`
    builds its response by looping over `MONEY_CONDITIONS` — five literals — so the server
    cannot hand back one of these four today. That is pinned in test_verbal_intake.py, not left
    to this file to imply. The seven-flag list that does include B10 New/Reno belongs to
    `/api/autofill`, which writes cell names and never calls this function."""
    g = ran["carryFromVerbal"]
    assert g["applied"]["applied"] == ["reno", "joint_filler"], (
        "a carried-through key did not reach toggleCondition")
    assert g["carryAfter"] == {**CARRY_BASE, "reno": True, "joint_filler": False}, (
        "the transcript said renovation and no joint filler; the switches say otherwise")
    assert g["conditionsAfter"] == BASE, (
        "a carried key was written onto the model, where migrateModel will drop it")
    # THE ONE THAT SEPARATES condOn FROM THE MODEL READ. Reading the model leaves Joint filler
    # reading "sw on" -- the crew filling joints on a job the transcript said had none -- and the
    # dependent switch below never greys out, because nothing turned its parent off.
    assert g["classesAfter"]["joint_filler"] == "sw", (
        "Joint filler is still ON after a transcript that said there is none: %r"
        % (g["classesAfter"],))
    assert g["classesAfter"]["remove_existing_jf"] == "sw inert", (
        "its dependent did not grey out, so the parent never actually moved")
    assert g["classesAfter"]["reno"] == "sw on"
    assert g["saves"] == 2, "cell_values is the only home these four have"
    assert g["humanOwned"] == [], "a verbal fill must not claim to be the estimator's answer"
    assert g["rerenders"] == 1, (
        "only Joint filler has a dependent, so only it pays for the full re-render; got %d"
        % g["rerenders"])
    assert g["focuses"] == ["joint_filler"], (
        "the re-render cost the caret and it was not put back: %r" % (g["focuses"],))


def test_a_carried_through_flag_that_is_already_right_is_left_alone(ran):
    """The same rule as the engine five, and the reason the gate could not be widened
    on its own.

    `toggleCondition` flips; it does not set. Both keys here are handed back at the value the
    page already holds — no dye, joints filled — which is the common case, since the transcript
    is usually describing a job the estimator already keyed in. A loop that called
    toggleCondition for everything the server accepted would turn Joint filler off on a job that
    needs it, and the only trace would be a kit missing from the estimate.

    Joint filler is the discriminating fixture in the other direction too: it is the one carried
    key whose default is ON, so a comparison reading `!!M.conditions.joint_filler` sees false
    against a true value here and toggles. Zero saves is the proof."""
    g = ran["carryAlreadyRight"]
    assert g["carryAfter"] == CARRY_BASE, "a switch that was already right was flipped"
    assert g["saves"] == 0, "it saved a change it did not need to make"
    assert g["painted"] == [] and g["rerenders"] == 0, "it repainted a switch that had not moved"
    assert g["applied"]["applied"] == ["dye", "joint_filler"], (
        "the panel must still report these as set — the estimator asked about them and the "
        "answer is that the form already agrees")


def test_a_click_on_a_carried_through_switch_still_works(ran):
    """The click path, straight through `toggleCondition` with no second argument — exactly what the
    delegated handler does. This is the path that broke: `toggleCondition` now asks `carrySpec(key)`
    first, and every test in this file errored with `ReferenceError: carrySpec is not defined`
    because the lifted scope had none of the carried-four machinery. None of those thirteen tests
    was about the carried four; a harness that lifts a function inherits everything that function
    starts reaching for.

    Three things have to hold. The answer lands on `carry`, NEVER on the model — `migrateModel`
    whitelists condition keys against `freshModel().conditions` and silently drops the rest, so a
    carried key stored there would look saved and come back missing. The click is the estimator's,
    so it is theirs from then on. And the draft is scheduled, because `cell_values` is the only
    place these four survive.

    Joint filler is clicked first on purpose: something depends on it, so it pays for the full
    re-render — all nine switches repainted and the caret put back. Dye has no dependents and takes
    the cheap one-node repaint, which is why the count below is one re-render and not two."""
    g = ran["carryClicked"]
    assert g["carryAfter"] == {**CARRY_BASE, "joint_filler": False, "dye": True}, (
        "a click has to move a carried switch from where hydrate() left it, not from empty")
    assert g["conditionsAfter"] == BASE, "a carried key was written onto the model"
    assert sorted(g["humanOwned"]) == ["dye", "joint_filler"], (
        "a real click did not mark the key as the estimator's")
    assert g["saves"] == 2, "cell_values is the only home these four have"
    assert g["rerenders"] == 1, (
        "only the key with a dependent should force a re-render; got %d" % g["rerenders"])
    assert g["focuses"] == ["joint_filler"], (
        "the re-render cost the caret and it was not put back: %r" % (g["focuses"],))


def test_a_value_that_is_not_a_boolean_is_not_a_decision(ran):
    """"true" is a string somebody's serialiser produced, not something a person chose. It reads as
    truthy to every careless check, and this one is not careless."""
    g = ran["nonBoolean"]
    assert g["applied"]["applied"] == []
    assert g["conditionsAfter"]["hard_bid"] is False
    assert g["saves"] == 0


def test_an_empty_extraction_changes_nothing(ran):
    """A dead or confused AI costs the estimator some typing. It never costs them the form they
    already filled in — and with no fields filled there is nothing to save either."""
    g = ran["empty"]
    assert g["applied"] == {"filled": [], "applied": [], "respected": []}
    assert g["conditionsAfter"] == BASE
    assert g["saves"] == 0 and g["events"] == [] and g["captionWrites"] == []


def test_a_condition_the_estimator_fixed_by_hand_survives_the_re_ask(ran):
    """THE PANEL RESPECTS THE HUMAN.

    The shape of this feature is read, fix the one thing it got wrong, re-read — the rate limit is
    three runs per five minutes, so that is most of the budget. The re-read sends the SAME
    transcript, so the AI returns the same flag with the same quote. Re-applying it puts the
    estimator's correction straight back where it was, and they have no way to tell except by
    watching the switch.

    A real click goes through toggleCondition with no second argument. That absence is what marks
    the key as theirs — the safe default, because a caller who forgets the flag costs the panel one
    re-fill rather than costing a person their decision."""
    g = ran["humanWins"]
    assert g["results"][0]["applied"]["applied"] == ["hard_bid"], "run one did not set it"
    assert g["humanOwned"] == ["hard_bid"], "the click was not recorded as the estimator's"
    third = g["results"][2]["applied"]
    assert third["respected"] == ["hard_bid"], (
        "the second run did not report the switch as the estimator's own")
    assert third["applied"] == [], "it claimed to have set a switch it was told to leave alone"
    assert g["conditionsAfter"]["hard_bid"] is False, (
        "the re-ask undid the correction the estimator made by hand")
    assert g["saves"] == 2, (
        "the third step wrote to the draft: one save for run one, one for the click, none for the "
        "run that changed nothing")


def test_the_panel_may_still_correct_its_own_earlier_answer(ran):
    """The mirror of the test above, and the reason `respected` is keyed on the CLICK rather than on
    "this key has been set before". A first pass that read prevailing wage wrong has to be fixable
    by a second pass; freezing every key the panel itself had touched would make the re-ask
    pointless."""
    g = ran["verbalMayCorrectItself"]
    assert g["results"][1]["applied"]["applied"] == ["prevailing_wage"]
    assert g["results"][1]["applied"]["respected"] == []
    assert g["conditionsAfter"]["prevailing_wage"] is False, (
        "the second reading did not correct the first")
    assert g["humanOwned"] == [], "the panel's own fill was mistaken for a person's click"


def test_one_hand_flip_does_not_freeze_the_other_four(ran):
    """Per key, not per run. An estimator who fixes Hard bid should still get Prevailing wage filled
    in for them — a panel that stopped filling anything the moment it was corrected once would have
    the estimator typing the whole form out of spite."""
    g = ran["humanFlipIsPerKey"]
    a = g["results"][1]["applied"]
    assert a["respected"] == ["hard_bid"] and a["applied"] == ["prevailing_wage"]
    assert g["conditionsAfter"]["hard_bid"] is True, "their own flip was reverted"
    assert g["conditionsAfter"]["prevailing_wage"] is True, "the untouched flag was not filled in"


def test_fields_and_a_flip_in_one_run_land_on_one_timer(ran):
    """Two calls to `saveSoon`, one PUT. saveSoon clears its own pending timer before arming a new
    one, which polish-intake-harness proves against the real clock; recorded here as the call count
    so the number is not mistaken for two writes to the draft."""
    g = ran["fieldsAndFlip"]
    assert g["applied"] == {"filled": ["project_name"], "applied": ["prevailing_wage"],
                            "respected": []}
    assert g["saves"] == 2
