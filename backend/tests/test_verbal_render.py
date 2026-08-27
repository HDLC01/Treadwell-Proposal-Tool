"""The verbal panel's own output — what the estimator actually reads.

backend/tests/test_verbal_intake.py owns which flags the server lets through, and
backend/tests/test_verbal_apply.py owns what the form does with them. This file owns the sentence
on the screen, and there is one failure here that is worse than any of them: THE PANEL CAN ASSERT
THE OPPOSITE OF WHAT THE ESTIMATOR SAID.

The evidence gate accepts a flag when the model's quote is verbatim in the transcript. That is the
right rule — it proves the words were spoken, and it is what stops the AI inventing a
prevailing-wage job out of a school district's name. What it cannot prove is that the words meant
the flag. "It is not a hard bid" contains, word for word, "a hard bid". The panel used to print that
crop after the word "because":

    Hard bid on — because you said: "a hard bid"

over a transcript that said the reverse, on a screen the estimator is being asked to check. The fix
is in two halves. The server now sends `context` — a raw slice of the transcript around the match —
INSTEAD OF `quote`, so the model's crop cannot reach the screen at all; and this panel prints those
words with the word "because" dropped, because it reports what was said and the estimator decides
whether it is a reason.

THE SECOND HALF IS THIS FILE'S ALONE. The server's matcher requires consecutive tokens, which kills
the mid-word match but cannot tell that "It is not local. Hard bid though." makes "not local hard
bid" a genuinely consecutive run across a full stop — the words really are in that order. Their
`_find_span` docstring and test_a_quote_cannot_be_stitched_across_a_full_stop leave that to be judged
by a person, and a person can only judge it if the sentence boundary is impossible to skim past. So a
multi-sentence excerpt is counted in words and broken onto its own lines, and that is asserted here,
because there is nowhere else it could be.

RUN, NOT READ. The markup comes out of seven branches, an escaper, a label table and a sentence
splitter. "The right words are on screen" is not a claim a source-text assertion can make, so the
harness lifts renderResult, evidenceHtml, sentencesOf, busy and label and executes them against real
server shapes.
"""

import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "verbal-render-harness.js"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def only_group(g):
    assert len(g["groups"]) == 1, "expected one group, got %r" % [x["heading"] for x in g["groups"]]
    return g["groups"][0]


def test_the_flag_prints_the_transcript_not_the_models_crop(ran):
    """THE BUG THIS FILE EXISTS FOR.

    The transcript says it is NOT a hard bid. The model quoted "a hard bid", which is verbatim, so
    the server was right to accept it as proof those words were spoken. Print that crop alone and
    the screen says the opposite of what the estimator told it — and the estimator is the person
    being asked to catch exactly that.

    With the surrounding words on screen the word "not" sits beside the switch, and the check the
    whole evidence gate exists to enable is one a person can actually perform."""
    g = ran["negatedQuote"]
    quote = g["quotes"][0]
    assert "it is not a hard bid" in quote, (
        "the estimator cannot see that they said NOT: %r" % quote)
    assert quote.startswith("the transcript says:"), quote
    assert "because" not in quote.lower(), (
        "the panel is still claiming the words are the REASON for the flag: %r" % quote)
    assert "a hard bid" in only_group(g)["items"][0], "the flag itself is not named"


def test_the_excerpt_is_marked_as_an_excerpt(ran):
    """Ellipses either side. `context` is eight or so words out of a transcript, and printing it
    with hard quote marks and nothing else would read as the whole of what was said — which invites
    the estimator to stop reading their own transcript, the opposite of the point."""
    quote = ran["negatedQuote"]["quotes"][0]
    assert "“…" in quote and "…”" in quote, quote


def test_a_multi_sentence_excerpt_is_counted_and_broken_up(ran):
    """THE HALF THE SERVER DELIBERATELY LEFT HERE.

    "not local hard bid" really is a consecutive run of words in "It is not local. Hard bid though."
    The matcher cannot tell that apart from a genuine quote and is not meant to try. What catches it
    is the estimator noticing that the evidence spans two sentences — which they will not, if the
    whole excerpt is one line of small grey text and the full stop is four pixels wide.

    So the count goes in words AND each sentence goes on its own line. Both, not either: the count is
    what a skimmer reads, the break is what makes it followable."""
    g = ran["twoSentences"]
    q = g["quotes"][0]
    assert "2 sentences, so read both" in q, (
        "nothing warns that the excerpt crosses a sentence boundary: %r" % q)
    assert "<br>" in g["html"], "the two sentences are run together onto one line"
    assert q.split("<br>") == [
        "the transcript says — 2 sentences, so read both: “…It is not local.",
        "Hard bid though…”"], q
    # Three reads "them all", not "both". Small, and two people read this copy all day.
    three = ran["acrossASentence"]["quotes"][0]
    assert "3 sentences, so read them all" in three, three
    assert three.count("<br>") == 2, three


def test_a_single_sentence_is_left_as_one_line(ran):
    """The break is a signal, so it has to mean something. Splitting an excerpt that never crossed a
    boundary would spend the signal on nothing and teach the estimator to ignore it."""
    q = ran["negatedQuote"]["quotes"][0]
    assert "<br>" not in q and "sentences" not in q, q


def test_with_no_context_it_says_so_rather_than_quoting_nothing(ran):
    """`context` is a str, never absent and never empty on an accepted condition, so this is the
    malformed-response path: a rolled-back server, a truncated body, a blank field. Empty quote marks
    would read as "the estimator said nothing", which is the one thing the gate has already proved
    false, so the panel says what happened and sends them to check it.

    `staleQuoteOnly` is the one that matters. `quote` is GONE from the wire on purpose — it was the
    model's crop, which is the whole reason this bug existed. A response still carrying one must not
    have it promoted back to evidence."""
    for key in ("noContext", "emptyContext", "staleQuoteOnly"):
        quote = ran[key]["quotes"][0]
        assert "the transcript says" not in quote, (
            "%s claims to be quoting the transcript with no context: %r" % (key, quote))
        assert "“" not in quote and "”" not in quote, (
            "%s printed empty quote marks: %r" % (key, quote))
        assert "nothing came back" in quote and "Check it yourself" in quote, quote
        assert "because" not in quote.lower()
    assert "tax exempt" not in ran["staleQuoteOnly"]["html"], (
        "the model's crop was resurrected out of the dead `quote` field")


def test_the_panel_never_reads_the_dead_quote_field(ran):
    """Belt to the braces above, over every branch instead of the fixtures'. The backend removed
    `quote`; a read anywhere in the panel puts "undefined" beside a price flag at best, and the
    model's crop back on screen at worst."""
    assert ran["sourceReadsQuote"] is False, (
        "frontend/js/polish-verbal.js reads `.quote` again — the server no longer sends it")


def test_a_switch_the_estimator_set_is_reported_not_reapplied(ran):
    """The panel respects the human, and says that it did. Silence would be worse than a re-flip:
    the estimator would not know the transcript still disagrees with the switch, so they could not
    change their own mind on the evidence. The words go up, the switch does not move, and the copy
    says whose call it is."""
    g = only_group(ran["respected"])
    assert g["heading"] == "You set these yourself"
    assert "Hard bid" in g["items"][0] and "left as you set it" in g["items"][0]
    assert "it is not a hard bid" in g["items"][0], (
        "the evidence is missing from the one group where it matters most")
    assert "Yours wins" in g["text"], g["text"]


def test_the_whole_panel_reads_in_one_pass(ran):
    """Five groups in the order a person reads them: what went in, what was switched, what was
    refused, what is still needed, and the one question. `remodel_tax` appears under "Not set" and
    is kept OUT of "Still needed", so nothing is asked for twice."""
    g = ran["filled"]
    assert [x["heading"] for x in g["groups"]] == [
        "Filled in", "Switches set", "Not set — you did not say", "Still needed", "One question"]
    assert g["groups"][0]["items"] == ["Project name: Blue Valley West", "City: Overland Park"]
    assert g["groups"][2]["cls"] == "warn", "the refused price flag is not marked as a warning"
    assert g["groups"][3]["text"] == "Bid date", (
        "remodel_tax is asked for twice: %r" % g["groups"][3]["text"])
    assert g["hasAskBox"] is True
    assert g["hidden"] is False


def test_an_applyverbal_without_respected_does_not_throw(ran):
    """polish-intake.js and polish-verbal.js are two script tags and two cache entries. A browser
    holding yesterday's copy of one of them must degrade to the old panel, not to a blank one."""
    g = only_group(ran["noRespectedKey"])
    assert g["heading"] == "Switches set"
    assert "Local job off" in g["items"][0]
    assert "out of town" in g["items"][0]


def test_a_transcript_is_not_markup(ran):
    """The context string is a RAW slice of the transcript — a person's own typing or dictation, with
    only whitespace collapsed. The panel writes innerHTML, so both branches that build an excerpt
    have to escape it, and only a fixture that crosses a sentence boundary reaches the second one."""
    html = ran["escaping"]["html"]
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "they are tax exempt" in html

    multi = ran["escapingAcrossSentences"]["html"]
    assert "<img" not in multi and "&lt;img" in multi, (
        "the multi-sentence branch does not escape the transcript: %r" % multi)
    # The one tag this branch writes itself, which is why "no tags at all" is not the assertion.
    assert "<br>" in multi and "onerror=" not in multi.replace("onerror=&quot;", "")


def test_nothing_matched_still_says_something_useful(ran):
    """An empty extraction is the estimator's cue to say more, not a blank box that looks broken."""
    g = only_group(ran["nothing"])
    assert g["heading"] == "Nothing to fill in"
    assert "naming the job" in g["text"]


def test_both_buttons_that_can_spend_a_run_go_busy(ran):
    """#verbal-answer-go is rendered INTO the output box, and during the second run it is the button
    the estimator is looking at — they just typed the answer above it. Left live, one impatient
    double click spends the third of three runs per five minutes, and the follow-up is normally the
    last one they have.

    Both come back on their own resting labels afterwards, from the two constants, so busy() cannot
    relabel a button it did not name."""
    b = ran["busy"]
    assert b["during"]["go"]["disabled"] is True
    assert b["during"]["ask"]["disabled"] is True, (
        "the follow-up button stays clickable while a run is in flight")
    assert b["during"]["go"]["text"] == b["during"]["ask"]["text"] == "Reading…"
    assert b["after"]["go"] == {"disabled": False, "text": b["goLabel"]}
    assert b["after"]["ask"] == {"disabled": False, "text": b["askLabel"]}
    assert b["goLabel"] == "Fill the form", (
        "the resting label no longer matches the button in frontend/polish-intake.html")


def test_the_follow_up_appends_and_runs_once(ran):
    """Unchanged behaviour, pinned because busy() now touches this button too. The answer is
    APPENDED to the transcript rather than sent alone — three runs per five minutes means the second
    pass is usually the last, so it has to carry everything. A blank answer spends nothing."""
    f = ran["followUp"]
    assert f["transcript"] == "Blue Valley West in Overland Park\ndue the third of September"
    assert f["runs"] == 1
    assert f["runsAfterBlank"] == 1, "a blank answer spent one of the three runs"


def test_the_one_question_is_not_asked_twice(ran):
    """`asked` is the budget guard. Once the follow-up has been put, the same question coming back
    from the second pass must not offer a third box."""
    assert ran["askedAlready"]["hasAskBox"] is False


def test_the_word_because_is_gone_from_the_panel(ran):
    """Belt to the braces above. The fixtures reach the branch that had it; this reaches every branch
    that could grow it back, because the mistake was not the string — it was framing a report of
    what was said as a claim about why."""
    assert ran["sourceHasBecause"] is False, (
        'frontend/js/polish-verbal.js says "because you said" again')
