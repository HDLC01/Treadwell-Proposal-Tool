"""The board's "email link opened" line, and the one thing it must never claim.

Half of Hanz's question — *"when a customer ... opens that chatbox with the specific project in
portal it is labeled as seen?"* — was already true: chat is the default view of the portal page,
and loading it marks the proposal viewed. The email half was invisible, so the portal now records
a click on the per-proposal link and this line surfaces it.

The card has to be careful about what it asserts. A click is evidence the EMAIL reached a
mailbox: the portal's landing page serves before anyone signs in, and Outlook SafeLinks and mail
scanners follow links on their own. So the wording is "email link opened", never "seen" or
"viewed", and the line disappears the moment there is a real view to report — otherwise it
competes with the Viewed column and reads like a second, contradictory answer.

Why it earns space on a crowded card: a proposal that has sat in Sent for a week is a different
problem depending on whether the email arrived. A follow-up call is the right move for "they are
still deciding" and a waste of time for "we have the wrong address", and the board could not tell
those apart before.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
JS = FRONTEND / "js" / "followups.js"
HTML = FRONTEND / "followups.html"


@pytest.fixture(scope="module")
def js():
    return JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def hint(js):
    m = re.search(r"function deliveryHint\(p, today\) \{(.*?)\n  \}", js, re.S)
    assert m, "deliveryHint() moved or was renamed"
    return m.group(1)


def test_the_hint_is_rendered_on_the_card(js):
    assert "${deliveryHint(p, today)}" in js, "the hint is defined but never drawn"


def test_it_only_speaks_while_the_proposal_is_still_unopened(hint):
    """Once somebody has actually viewed the portal, the question is answered. Leaving the line
    up would put a weaker claim next to a stronger one on the same card."""
    assert 'if (st !== "sent") return "";' in hint, (
        "the hint is not restricted to un-viewed proposals")


def test_it_says_nothing_when_no_click_was_recorded(hint):
    assert "if (!p.link_clicked_at) return \"\";" in hint


def test_it_never_calls_a_click_seen_or_viewed(hint):
    """THE wording guarantee. A mail scanner following a link must not read on the board as the
    customer having looked at the bid.

    Checks the text the card actually EMITS. The first version of this test searched the whole
    function and tripped over the word "viewed" inside an explanatory comment — a test failing
    on its own documentation proves nothing about the product."""
    code = "\n".join(l for l in hint.split("\n") if not l.strip().startswith("//"))
    code = re.sub(r'title="[^"]*"', "", code)             # the tooltip carries the caveat
    emitted = " ".join(re.findall(r"`([^`]*)`", code)).lower()
    assert emitted, "no template literal found; the label may have moved"
    for word in ("seen", "viewed", "read it", "opened the proposal"):
        assert word not in emitted, (
            "the visible label claims %r, which a link click does not prove" % word)
    assert "email link opened" in emitted


def test_the_tooltip_states_the_caveat_rather_than_hiding_it(hint):
    """Somebody WILL read this as proof the customer saw the proposal. The card should say why
    it isn't, in the place they look when they wonder."""
    tip = re.search(r'title="([^"]*)"', hint)
    assert tip, "no tooltip on the hint"
    text = tip.group(1).lower()
    assert "not proof" in text
    assert "scanner" in text or "signs in" in text


def test_it_prefers_the_most_recent_click_for_the_date(hint):
    assert "p.last_link_clicked_at || p.link_clicked_at" in hint, (
        "the date should be the latest click, falling back to the first")


def test_it_does_not_invent_a_status_or_move_the_card(hint):
    """The line is a report. It must not touch the bucket, the cadence, or the drag rules."""
    for forbidden in ("proposal_status =", "canMove", "movePlan", "column(", "fetch("):
        assert forbidden not in hint, "deliveryHint does more than describe: %s" % forbidden


def test_the_style_exists_and_is_not_shouting(js):
    css = HTML.read_text(encoding="utf-8")
    assert ".fu-delivered" in css, "no style for the hint; it would inherit body text size"
    rule = re.search(r"\.fu-delivered \{([^}]*)\}", css)
    assert rule, "expected a single .fu-delivered rule"
    body = rule.group(1)
    size = re.search(r"font-size:\s*([\d.]+)px", body)
    assert size and float(size.group(1)) <= 11, (
        "the hint should be quieter than the project name — it is reassurance, not an action")
