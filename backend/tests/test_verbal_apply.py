"""applyVerbal — putting an accepted extraction onto the estimator's screen.

backend/tests/test_verbal_intake.py owns the SERVER half: which flags are allowed through at all,
and why a price flag needs a verbatim quote. This file owns what happens after they are allowed
through, and there are exactly two ways that goes wrong, both silent:

  * **A switch that was already right gets flipped.** `toggleCondition` is a toggle, not a setter.
    The obvious loop — for every condition the server accepted, call toggleCondition — turns a
    correct form wrong. Nothing on screen says so; the only evidence is a price that moved. This
    is the reason the file exists.
  * **A field is filled without an event.** The draft saves off the form's own input handling, so
    assigning `.value` alone fills the boxes and saves none of it. The estimator sees a complete
    form, reloads, and finds it empty.

RUN, NOT READ. Both failures live in the relationship between applyVerbal, toggleCondition and the
model — a source-text assertion sees a loop and a correctly-named call and passes. The harness
lifts the real functions and executes them against the smallest form they touch, so "already
right" is observable as a save that did not happen.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "verbal-apply-harness.js"


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
    assert g["applied"] == {"filled": [], "applied": ["prevailing_wage"]}
    assert g["conditionsAfter"]["prevailing_wage"] is True
    assert g["saves"] == 1, "the change was never scheduled to save"
    assert g["countyNoteRepaints"] == 1, (
        "the county note still quotes the old state of the switches")


def test_a_flag_that_is_already_right_is_left_alone(ran):
    """THE BUG THIS FILE EXISTS FOR.

    `toggleCondition` flips; it does not set. An extraction that agrees with the form — which is
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


def test_a_field_is_filled_through_a_real_input_event(ran):
    """Setting `.value` alone is the failure that looks most like success: every box is filled, the
    form looks finished, and nothing was saved. The event has to bubble, because the handler that
    owns the draft is delegated from the form rather than bound per input."""
    g = ran["fields"]
    assert g["inputValues"] == {"project_name": "Blue Valley West", "city": "Overland Park",
                                "bid_date": "2026-09-03"}
    assert [e["type"] for e in g["events"]] == ["input", "input", "input"]
    assert all(e["bubbles"] for e in g["events"]), (
        "the input events do not bubble, so the form's own handler never sees them")
    assert g["applied"]["filled"] == ["project_name", "city", "bid_date"]


def test_a_condition_nobody_wired_up_sets_nothing(ran):
    """`isCondition` is the gate, and it is the same one the switches themselves are built from.
    A county key is included in the fixture deliberately: the server strips those, and if that ever
    regressed this is the second place it would have to get past."""
    g = ran["unknownCondition"]
    assert g["applied"]["applied"] == []
    assert g["conditionsAfter"] == {"local": True, "hard_bid": False, "prevailing_wage": False,
                                    "taxable": True, "remodel_tax": False}
    assert g["saves"] == 0


def test_a_value_that_is_not_a_boolean_is_not_a_decision(ran):
    """"true" is a string somebody's serialiser produced, not something a person chose. It reads as
    truthy to every careless check, and this one is not careless."""
    g = ran["nonBoolean"]
    assert g["applied"]["applied"] == []
    assert g["conditionsAfter"]["hard_bid"] is False
    assert g["saves"] == 0


def test_an_empty_extraction_changes_nothing(ran):
    """A dead or confused AI costs the estimator some typing. It never costs them the form they
    already filled in."""
    g = ran["empty"]
    assert g["applied"] == {"filled": [], "applied": []}
    assert g["conditionsAfter"] == {"local": True, "hard_bid": False, "prevailing_wage": False,
                                    "taxable": True, "remodel_tax": False}
    assert g["saves"] == 0 and g["events"] == []
