"""Verbal intake for the Polish beta — what an estimator says, turned into intake fields.

Hanz, 2026-08-25: the estimator talks, the AI fills what it can and asks ONCE for what is missing,
and if they do not have it they carry on. Reaching the normal intake form stays optional.

WHAT THIS FILE IS DEFENDING, and it is one thing above all others: **an extraction model must not
be able to move a price by inferring something nobody said.**

Five toggles on this form change what the customer is charged — local, hard_bid, prevailing_wage,
taxable, remodel_tax — and every one of them is exactly the sort of thing a helpful model will
deduce. A school district in the project name looks like prevailing wage. The word "renovation"
looks like remodel tax. A Kansas City address looks local. Each of those inferences is plausible,
none of them was said, and all of them are invisible once the toggle is on: the estimator sees a
filled-in form, not a guess.

So a flag is only accepted when the model returns a VERBATIM QUOTE and the server can still find
that quote in the transcript IT sent. The model supplies the claim; the transcript supplies the
proof; the model never supplies both. Anything it cannot quote is dropped and named in
`unsupported`, which is what the page asks the estimator about.

The second thing defended here is narrower and sharper: **nothing in this path may write a
county.** `county_remodel_rate` is null for "nobody said" and 0 for "we know, and it is nothing"
(Missouri exempts remodel labour), and those two are indistinguishable once written. A guessed 0
silently underprices the job with nothing on screen to notice. The county picker on the form is
the only thing allowed to set it, so the four county keys are stripped unconditionally rather than
merely left out of the prompt.

Every test here is a pure function over a dict and a string — no CLI, no network — because the
rules are the product and they should be cheap to interrogate.
"""

import pytest

import verbal_intake as V


TRANSCRIPT = (
    "Okay so this one is Blue Valley West High School, 16200 Antioch Road, Overland Park Kansas "
    "66085. It's a hard bid, going out through the district, and they told me it is prevailing "
    "wage. Bid is due the third of September. Contact is Dana Whitfield, "
    "dana.whitfield@bvschools.org."
)


# ── the evidence gate ────────────────────────────────────────────────────────
def test_a_flag_the_estimator_actually_said_is_accepted():
    """The straightforward half: the words are in the transcript, so the flag stands."""
    out = V.clean({"conditions": {
        "prevailing_wage": {"value": True, "quote": "they told me it is prevailing wage"},
    }}, TRANSCRIPT)
    assert out["conditions"]["prevailing_wage"]["value"] is True
    assert out["unsupported"] == []


def test_a_flag_the_model_inferred_is_thrown_away():
    """THE WHOLE POINT OF THE FILE. "Blue Valley West High School" is in the transcript and a
    school really does suggest prevailing wage — but nobody said it, so the model has to write a
    justification it cannot source, and that is what gets caught.

    The value is not merely ignored: the flag is named in `unsupported`, because the estimator is
    about to be asked about it and a silently-missing price flag is the failure this feature would
    otherwise introduce."""
    out = V.clean({"conditions": {
        "prevailing_wage": {"value": True,
                            "quote": "a school district project is prevailing wage"},
    }}, TRANSCRIPT)
    assert "prevailing_wage" not in out["conditions"]
    assert out["unsupported"] == ["prevailing_wage"]
    assert "prevailing_wage" in out["missing"], (
        "an unsupported flag has to reach the estimator as something still to answer")


def test_a_paraphrase_is_not_a_quote():
    """A gate that accepted a close paraphrase would not be a gate: the model could write down
    what it inferred, phrase it like the transcript, and have it accepted as what it heard."""
    out = V.clean({"conditions": {
        "hard_bid": {"value": True, "quote": "this is a competitively bid project"},
    }}, TRANSCRIPT)
    assert out["conditions"] == {}
    assert out["unsupported"] == ["hard_bid"]


def test_a_one_word_quote_cannot_unlock_anything():
    """"yes" appears in most transcripts and would open any flag the model liked. A quote has to
    be long enough to carry a claim — two words and eight characters is the smallest thing that
    can ("hard bid", "no sales tax")."""
    for weak in ("yes", "it", "is", "a", "bid", "okay"):
        out = V.clean({"conditions": {"taxable": {"value": False, "quote": weak}}}, TRANSCRIPT)
        assert out["conditions"] == {}, "%r was accepted as evidence" % weak


def test_the_gate_proves_the_words_were_said_not_that_they_mean_what_is_claimed():
    """THE LIMIT OF THIS MECHANISM, written down so nobody mistakes it for more than it is.

    "the district" really is in the transcript, so a model that offers it as grounds for "not
    taxable" clears the gate. Provenance is checkable by machine; relevance is not, and any
    keyword rule that tried would reject real evidence phrased unexpectedly.

    What the gate DOES buy is that the model can no longer invent the words. Everything it offers
    was actually said, which is why the accepted quote is returned alongside the flag: the page
    shows "not taxable — because you said: …" and the estimator judges the relevance in one
    glance. That is the review this feature is built around, not a substitute for it."""
    out = V.clean({"conditions": {
        "taxable": {"value": False, "quote": "going out through the district"}}}, TRANSCRIPT)
    assert out["conditions"]["taxable"]["quote"] == "going out through the district", (
        "the flag was accepted without keeping the words it rests on, so nothing on screen can "
        "show the estimator what it was based on")


def test_punctuation_and_case_do_not_break_a_real_quote():
    """Dictation punctuates by guesswork and a model asked to quote will normally re-punctuate
    what it read, so comparing raw strings would reject genuine evidence — and an estimator whose
    true answers keep being thrown away stops using the feature.

    What survives normalisation is the sequence of WORDS, which is what makes a quote evidence.
    Stemming or fuzzy matching would go too far the other way; see evidence_key."""
    out = V.clean({"conditions": {
        "hard_bid": {"value": True, "quote": "It's a HARD BID, going out through the district"},
    }}, TRANSCRIPT)
    assert out["conditions"]["hard_bid"]["value"] is True


def test_a_quote_from_a_different_conversation_does_not_count():
    """The gate runs against the transcript the SERVER sent, not against anything the caller
    supplies alongside the answer. A model cannot hand over both the claim and the proof of it."""
    out = V.clean({"conditions": {
        "local": {"value": True, "quote": "it is right here in Olathe"},
    }}, TRANSCRIPT)
    assert out["conditions"] == {}


def test_a_false_flag_still_needs_evidence():
    """Turning a flag OFF moves money too — `taxable` defaults on, so an unsupported False is a
    tax silently dropped off the bid. The gate is about whether it was SAID, not which way."""
    said = V.clean({"conditions": {
        "hard_bid": {"value": False, "quote": "It's a hard bid"}}}, TRANSCRIPT)
    assert said["conditions"]["hard_bid"]["value"] is False
    guessed = V.clean({"conditions": {
        "taxable": {"value": False, "quote": "schools are tax exempt"}}}, TRANSCRIPT)
    assert guessed["conditions"] == {}


def test_a_condition_with_no_quote_at_all_is_dropped():
    for shape in ({"value": True}, {"value": True, "quote": ""}, {"value": True, "quote": None}):
        out = V.clean({"conditions": {"remodel_tax": shape}}, TRANSCRIPT)
        assert out["conditions"] == {}, shape


def test_a_condition_whose_value_is_not_a_boolean_is_dropped():
    """"true", 1 and "yes" all read as true to a careless caller and none of them is a decision
    somebody made. The toggle is a boolean or it is absent."""
    for bad in ("true", 1, "yes", None, {}):
        out = V.clean({"conditions": {
            "local": {"value": bad, "quote": "It's a hard bid, going out through the district"}}},
            TRANSCRIPT)
        assert out["conditions"] == {}, bad


# ── the county, which nothing here may touch ─────────────────────────────────
@pytest.mark.parametrize("key", V.BANNED_KEYS)
def test_no_county_key_survives_whatever_the_model_returns(key):
    """`county_remodel_rate` is null for "nobody said which county" and 0 for "we know, and it is
    nothing" — Missouri exempts remodel labour. Those two are indistinguishable once written, so a
    guessed 0 underprices the job with nothing on screen to notice.

    Enforced HERE rather than trusted to the prompt. A model that returns the key anyway must not
    be able to reach the draft with it, and prompts are not a mechanism."""
    out = V.clean({key: "Johnson", "project_name": "Blue Valley West"}, TRANSCRIPT)
    assert key not in out["fields"]
    assert out["fields"]["project_name"] == "Blue Valley West", (
        "stripping the county took the rest of the extraction with it")


# ── the ordinary fields ──────────────────────────────────────────────────────
def test_the_plain_fields_come_through():
    out = V.clean({"project_name": "Blue Valley West", "address": "16200 Antioch Road",
                   "city": "Overland Park", "state": "ks", "zip": "66085",
                   "contact_name": "Dana Whitfield",
                   "contact_email": "dana.whitfield@bvschools.org",
                   "bid_date": "2026-09-03"}, TRANSCRIPT)
    assert out["fields"]["state"] == "KS", "the state was not normalised to two upper-case letters"
    assert out["fields"]["bid_date"] == "2026-09-03"
    assert out["fields"]["contact_email"] == "dana.whitfield@bvschools.org"


@pytest.mark.parametrize("key,bad", [
    ("bid_date", "September 3rd"), ("bid_date", "2026-9-3"), ("bid_date", "next Thursday"),
    ("state", "Kansas"), ("state", "K"), ("state", "12"),
    ("contact_email", "dana at bvschools"), ("contact_email", "dana@bvschools"),
    ("zip", "660"), ("zip", "sixty six thousand"),
])
def test_a_value_the_form_cannot_use_is_dropped_rather_than_passed_on(key, bad):
    """A malformed date is worse than no date: it lands in a date input, looks deliberate, and the
    bid is due when it is due. Same for the rest — the form's own validation is not a safety net
    when the field arrives pre-filled and unread."""
    assert key not in V.clean({key: bad}, TRANSCRIPT)["fields"]


def test_a_dead_or_confused_ai_never_costs_the_estimator_the_draft():
    """leads.py's rule, and it holds here: "a dead AI costs the estimator some typing; it never
    costs them the draft". Nothing in this path may raise on a shape it did not expect."""
    for junk in (None, [], "", 0, {"conditions": "yes"}, {"conditions": {"local": "true"}},
                 {"missing": "everything"}, {"reasoning": []}):
        out = V.clean(junk, TRANSCRIPT)
        assert out["fields"] == {} and out["conditions"] == {}


def test_only_the_known_condition_names_are_accepted():
    """A key nobody wired up is not a toggle, and inventing one here would show up as a flag the
    form silently ignores rather than as an error anyone sees."""
    out = V.clean({"conditions": {
        "union_job": {"value": True, "quote": "It's a hard bid, going out through the district"},
    }}, TRANSCRIPT)
    assert out["conditions"] == {}


# ── merging into a project that already has a takeoff ────────────────────────
def test_the_conditions_merge_rather_than_replace():
    """`polish_estimate` carries every area, material and crew line of a takeoff. The intake owns
    only `conditions` inside it, and replacing that object would delete a finished takeoff's
    settings on the strength of one spoken sentence."""
    existing = {"local": True, "taxable": True, "prevailing_wage": False}
    out = V.merge_conditions(existing, {"prevailing_wage": {"value": True, "quote": "x"}})
    assert out == {"local": True, "taxable": True, "prevailing_wage": True}
    assert existing["prevailing_wage"] is False, "the caller's dict was mutated"


def test_merging_ignores_anything_that_is_not_a_known_boolean_flag():
    out = V.merge_conditions({"local": True},
                             {"county_remodel_rate": {"value": True, "quote": "x"},
                              "local": {"value": "yes", "quote": "x"}})
    assert out == {"local": True}, out


# ── the one question ─────────────────────────────────────────────────────────
def test_the_question_is_carried_through_and_bounded():
    """The estimator is asked ONCE — the rate limit is three runs per five minutes per project, so
    a first pass plus one re-ask already spends two of them. A question long enough to scroll is a
    question that does not get read, and this is the only one they get."""
    out = V.clean({"question": "Which county is the job in?"}, TRANSCRIPT)
    assert out["question"] == "Which county is the job in?"
    assert len(V.clean({"question": "x" * 5000}, TRANSCRIPT)["question"]) <= 400
