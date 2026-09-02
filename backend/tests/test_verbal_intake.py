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
that quote in the transcript IT sent, as a consecutive run of whole words. The model supplies the
claim; the transcript supplies the proof; the model never supplies both. Anything it cannot quote
is dropped and named in `unsupported`, which is what the page asks the estimator about.

THE SECOND HALF OF THAT GATE, and it is the half that was missing: what comes back with an
accepted flag is `context` — the transcript's own text either side of the match — and never the
model's quote. Word-for-word true is not the same as true: a transcript saying "it is not a hard
bid" and a model quoting the three words "a hard bid" is an honest quote of an inverted claim, and
the panel used to print that crop next to the word "because". Widening the display to the
surrounding words is what lets the estimator catch it, which is the review this feature is built
around rather than a substitute for it.

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
    """THE LIMIT OF THIS MECHANISM, written down so nobody mistakes it for more than it is — and
    what the display does about it.

    "going out through the district" really is in the transcript, so a model that offers it as
    grounds for "not taxable" clears the gate. Provenance is checkable by machine; relevance is
    not, and any keyword rule that tried would reject real evidence phrased unexpectedly.

    So the gate hands the judgement to the estimator, and the ONLY way that works is if what
    reaches the screen is the transcript's own words rather than the model's selection of them.
    That is `context`: the match plus eight words either side, in the estimator's punctuation.
    The page renders `the transcript says: "…{context}…"`, and one glance covers both the
    provenance and the relevance."""
    out = V.clean({"conditions": {
        "taxable": {"value": False, "quote": "going out through the district"}}}, TRANSCRIPT)
    ctx = out["conditions"]["taxable"]["context"]
    assert "going out through the district" in ctx, (
        "the flag was accepted without keeping the words it rests on, so nothing on screen can "
        "show the estimator what it was based on")
    assert "It's a hard bid" in ctx, (
        "the context stopped at the quote, so the estimator sees the model's crop and not the "
        "sentence it came out of — which is the whole point of returning context")
    assert "quote" not in out["conditions"]["taxable"], (
        "the model's own crop is still on the accepted condition, so the panel can go back to "
        "printing it — see the cropped-negation test below for what that costs")


def test_a_quote_cropped_out_of_its_own_negation_shows_the_negation_too():
    """THE DEFECT THIS FIELD EXISTS FOR, and it was live.

    "a hard bid" is three words the estimator really said — inside the sentence "it is NOT a hard
    bid". The gate cannot refuse it and should not try: every word is provably in the transcript,
    and a machine that tried to judge which side of a negation a phrase sits on would start
    throwing away real evidence.

    What it CAN do is refuse to let the model choose which words the estimator reads back. The
    accepted flag carries the transcript's text around the match, so "not a hard bid" arrives on
    screen next to a switch that says Hard bid — and the person who said it sees the contradiction
    immediately. That is the human check working, not a hole in the gate."""
    transcript = ("This one is the Olathe fire station on Ridgeview. It is not a hard bid, they "
                  "just want a number by Friday for budgeting.")
    out = V.clean({"conditions": {
        "hard_bid": {"value": True, "quote": "a hard bid"}}}, transcript)
    assert out["conditions"]["hard_bid"]["value"] is True, (
        "the gate started judging meaning — see the docstring for why it must not")
    assert "not a hard bid" in out["conditions"]["hard_bid"]["context"], (
        "the panel would print the model's crop and the estimator would read their own words back "
        "with the negation cut off it")


def test_a_quote_cannot_match_in_the_middle_of_a_word():
    """The old check was a substring search over the transcript with punctuation stripped, so
    "hard bid" was found inside "a shard bidding floor" — words that were never said, offered as
    proof of a flag that moves money.

    Comparing whole tokens in sequence anchors both ends of every word for free, which is why the
    fix is a tokeniser and not a regex with \\b in it: \\b would still have to be built out of the
    same normalisation, twice."""
    transcript = ("We are pouring over a shard bidding floor at the Prevailing Wages Cafe on "
                  "Locally Grown Road, and the slab is taxable to the penny.")
    for quote in ("hard bid", "prevailing wage", "local job"):
        out = V.clean({"conditions": {"hard_bid": {"value": True, "quote": quote}}}, transcript)
        assert out["conditions"] == {}, "%r was matched inside a longer word" % quote


def test_a_quote_cannot_be_stitched_across_a_full_stop():
    """Punctuation is dropped from the comparison so that dictation's guessed commas do not throw
    away real evidence — but dropping it also let a quote run straight through the end of one
    sentence and into the next. "It is not local. Hard bid though." supported a quote of "local
    hard bid", which is a sentence nobody spoke.

    A consecutive-token match does not fix that on its own, and it is not meant to: the words ARE
    consecutive. What fixes it is the same thing that fixes the crop — the estimator reads the
    context and sees two sentences. This test pins the case so the next person to widen the
    matcher knows it is here."""
    transcript = "Talked to Dana this morning. It is not local. Hard bid though, due Friday."
    out = V.clean({"conditions": {
        "hard_bid": {"value": True, "quote": "not local hard bid"}}}, transcript)
    assert "not local. Hard bid" in out["conditions"]["hard_bid"]["context"], (
        "the flag was accepted on words spanning two sentences with nothing on screen to show it")


def test_the_context_is_the_transcript_and_not_a_normalised_copy_of_it():
    """It has to READ like something the estimator said. The matcher works on case-folded,
    punctuation-free tokens, and returning THAT ("its a hard bid going out through the district")
    would look like a machine talking and hide the very punctuation the estimator needs to see —
    the full stop that separates two claims.

    So the tokeniser records each word's offsets into the original string and the context is a
    slice of it. Newlines collapse, because dictation arrives with them mid-sentence; nothing
    else is touched.

    The slice runs from the first word to the last and stops there, which is why the closing full
    stop is not in it. The page wraps the value in ellipses — `the transcript says: "…{context}…"`
    — so a context that began or ended mid-sentence reads as one either way."""
    transcript = "Bid is\nhard,   like  it always is here.\nDue Friday."
    out = V.clean({"conditions": {
        "hard_bid": {"value": True, "quote": "bid is hard"}}}, transcript)
    ctx = out["conditions"]["hard_bid"]["context"]
    assert ctx == "Bid is hard, like it always is here. Due Friday", ctx


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
    be able to reach the draft with it, and prompts are not a mechanism.

    THE MECHANISM IS THE WHITELIST, and this test is what proves it: `fields` is built by walking
    TEXT_FIELDS, so a key that is not on that tuple has nowhere to arrive. There used to be an
    explicit `pop` of BANNED_KEYS after that loop which looked like the enforcement and could
    never fire — the two tuples do not intersect, so it removed keys that were never added. It is
    deleted; this test passed before it existed and passes after it, because the whitelist was
    always doing the work. BANNED_KEYS stays as the parametrisation, so the ban keeps a name and a
    failing case."""
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


@pytest.mark.parametrize("bad", [3, True, False, 0, 1.5, {"project_name": 1}, "project_name"])
def test_a_missing_list_that_is_not_a_list_does_not_raise(bad):
    """THIS ONE REACHED PRODUCTION AS A 500. `{"missing": 3}` walked past `ai.get("missing") or []`
    — 3 is truthy — into a comprehension that iterates it, and `TypeError: 'int' object is not
    iterable` came out of a `clean()` call that sat OUTSIDE the route's try block. The estimator
    got a blank failure AND one of their three runs per five minutes was already spent on it.

    `or []` guards falsiness; `isinstance(..., list)` guards the thing that actually matters. A
    string is the interesting case among these: it is iterable, so it never raised, and it also
    must not become a list of single characters."""
    out = V.clean({"missing": bad, "project_name": "Blue Valley West"}, TRANSCRIPT)
    assert out["missing"] == [], out["missing"]
    assert out["fields"]["project_name"] == "Blue Valley West", (
        "one bad key took the rest of a good extraction with it")


@pytest.mark.parametrize("key", ["project_name", "address", "city", "contact_name"])
@pytest.mark.parametrize("bad", [["Blue", "Valley"], {"name": "Blue"}, 42, True, 3.5, None])
def test_a_field_that_is_not_a_string_is_not_a_value_anybody_said(key, bad):
    """`str(["Blue", "Valley"])` is "['Blue', 'Valley']", and that is what landed in the project
    name box — brackets, quotes and all, looking exactly as deliberate as a real answer, because
    nothing on the form distinguishes a filled field from a correctly filled one.

    Numbers are refused for the same reason and one more: `str()` on them has already lost
    information a form needs. A zip of 06085 arrives as 6085 and no amount of later validation
    gets the leading zero back."""
    assert key not in V.clean({key: bad}, TRANSCRIPT)["fields"]


def test_a_field_long_enough_to_be_the_whole_transcript_is_cut_down():
    """Bounded the same way `question` is. A model that pastes its input back into project_name
    gives the intake form a value nothing on screen can show and the draft blob has to carry on
    every save — and the blob is PUT whole, every time.

    Free text is TRUNCATED because a clipped project name is visible and the estimator fixes it;
    a structured field over the cap is DROPPED, because a clipped email address is a plausible
    address for somebody who does not exist."""
    out = V.clean({"project_name": "B" * 5000,
                   "contact_email": ("a" * 400) + "@bvschools.org"}, TRANSCRIPT)
    assert len(out["fields"]["project_name"]) == 300, len(out["fields"].get("project_name", ""))
    assert "contact_email" not in out["fields"], (
        "a 400-character local part still matched the email pattern and was passed on")


def test_only_the_known_condition_names_are_accepted():
    """A key nobody wired up is not a toggle, and inventing one here would show up as a flag the
    form silently ignores rather than as an error anyone sees."""
    out = V.clean({"conditions": {
        "union_job": {"value": True, "quote": "It's a hard bid, going out through the district"},
    }}, TRANSCRIPT)
    assert out["conditions"] == {}


# ── merging into a project that already has a takeoff ────────────────────────
# There were two tests here for `merge_conditions()`, and they were the only callers it ever had.
# The route RETURNS and does not write, so nothing on the server merges anything; the merge that
# really happens is applyVerbal setting each switch through toggleCondition, which
# backend/tests/test_verbal_apply.py pins — including the "already right" case that a naive
# server-side merge would never have caught. Two rules for one decision is how they drift apart.


# ── the one question ─────────────────────────────────────────────────────────
def test_the_question_is_carried_through_and_bounded():
    """The estimator is asked ONCE — the rate limit is three runs per five minutes per project, so
    a first pass plus one re-ask already spends two of them. A question long enough to scroll is a
    question that does not get read, and this is the only one they get."""
    out = V.clean({"question": "Which county is the job in?"}, TRANSCRIPT)
    assert out["question"] == "Which county is the job in?"
    assert len(V.clean({"question": "x" * 5000}, TRANSCRIPT)["question"]) <= 400
