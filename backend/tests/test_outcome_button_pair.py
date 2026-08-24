"""The card's two outcome buttons must be named as a matched pair.

THE HISTORY IS THE WHOLE REASON THIS FILE EXISTS. They shipped as "Mark as closed" and "Lost".
Hanz read that on a real card and asked, in as many words: "mark as closed and lost are the same?"

They were never the same. One posts the by-hand won mark; the other opens the reason dialog and can
put a bid on hold instead of killing it. They are opposites. But only ONE of them was phrased as an
instruction, and the word "closed" sitting immediately beside "Lost" reads as though it might BE
lost - closed, as in closed out, as in gone. The ambiguity was in the naming, not the behaviour.

So: both are now "Mark as won" and "Mark as lost", and this asserts the SHAPE rather than the two
strings. Renaming one of them and leaving the other is what has to fail here, because that is the
state the card was in when a rep stopped and asked what it meant.
"""

import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"

# Both buttons carry "Mark as " so they read as one pair of choices rather than a label and a verb.
SHARED_PREFIX = "Mark as "


def _card_actions_source():
    js = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
    m = re.search(r"function cardActions[\s\S]{0,1600}?\n  \}", js)
    assert m, "cardActions is no longer shaped the way this test finds it"
    return m.group(0)


def _labels():
    body = _card_actions_source()
    out = {}
    for attr in ("data-won", "data-lost"):
        hit = re.search(attr + r'="\$\{id\}"[^>]*>([^<]+)</button>', body)
        assert hit, "no button in cardActions carries %s any more" % attr
        out[attr] = hit.group(1).strip()
    return out


def test_both_outcome_buttons_are_phrased_the_same_way():
    labels = _labels()
    for attr, text in labels.items():
        assert text.startswith(SHARED_PREFIX), (
            "%s reads %r. Its partner is phrased %r..., and one button written as an instruction "
            "beside one that is not is exactly what made a rep ask whether the two were the same "
            "thing." % (attr, text, SHARED_PREFIX))


def test_each_button_says_which_outcome_it_is():
    """"Mark as closed" failed this: it named the act, not the result."""
    labels = _labels()
    assert "won" in labels["data-won"].lower(), labels["data-won"]
    assert "lost" in labels["data-lost"].lower(), labels["data-lost"]
    assert labels["data-won"] != labels["data-lost"], labels


def test_neither_button_calls_itself_closed():
    """"Closed" is the word that caused the question, and it is ambiguous in both directions.

    Closing a bid out is what the LOST dialog's own confirm button says ("Close it out"), which is
    correct there - it sits under a heading that has already named the reason. On the card, with no
    reason chosen yet and a Lost button beside it, "closed" could mean either outcome.
    """
    for attr, text in _labels().items():
        assert "closed" not in text.lower(), (
            "%s reads %r; \"closed\" beside the other outcome reads as though it might mean lost"
            % (attr, text))


def test_the_titles_do_not_contradict_the_labels():
    """The hover text has to agree with the button. The won button's title used to say "marks this
    closed", which re-introduced the same word the label had just dropped."""
    body = _card_actions_source()
    won = re.search(r'data-won="\$\{id\}"[^>]*title="([^"]*)"', body)
    lost = re.search(r'data-lost="\$\{id\}"[^>]*title="([^"]*)"', body)
    assert won and lost, "one of the outcome buttons has no title"
    assert "won" in won.group(1).lower(), won.group(1)
    assert "closed" not in won.group(1).lower(), (
        "the won button's title still says \"closed\": %r" % won.group(1))
