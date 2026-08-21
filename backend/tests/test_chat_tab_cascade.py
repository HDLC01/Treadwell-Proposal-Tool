"""The chat tab's colour must not disable the states the strip already shows.

Hanz, 2026-08-21: "also move that tab to the leftmost and make it a different color tab I guess so
its just intuittive to always look there."

WHY THIS FILE EXISTS AT ALL, because the history is the point. The first version of this check lived
in test_drawer_renders.py and asserted that .is-done / .needs / [aria-selected="true"] were declared
LATER IN THE FILE than the chat tint. They were, so it passed. But the tint was written as
`.dtabs .step#dtab-chat`, and one id outweighs any number of classes, so it beat all three whatever
the order. Measured in a real browser on staging, on a Test project with one unread message: the
chat tab carried `needs is-active` and aria-selected="true" and still painted #eff5fc - not the
selected white, not the needs pink. Unread chat stopped looking urgent and the open tab stopped
looking open, and a test written to prevent exactly that reported success.

So these tests compare WEIGHT first and use source order only as the tie-break, which is how the
cascade actually resolves. That ordering of concerns is the whole lesson: among unequal weights,
order is irrelevant.

Third instance of this class of bug in this repo - after a class `display` rule beating the `hidden`
attribute, and `opacity: 0` still taking clicks. Hence the second test, which bans the shape rather
than the instance.
"""

import pathlib
import re

HTML = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "portal.html"

# The three states the tab strip paints, each of which must out-rank or tie the chat tint.
STATE_RULES = (
    r"\.dtabs \.step\.is-done",
    r"\.dtabs \.step\.needs",
    r"\.dtabs \.step\[aria-selected='true'\]".replace("'", '"'),
)

CHAT_RULE = r"\.dtabs \.step\[data-sec='chat'\]".replace("'", '"')


def _weigh(sel):
    """(ids, classes) for one simple selector.

    Enough for this strip: no !important anywhere in it, and the tabs carry no inline styles, so
    the (ids, classes) pair decides every one of these comparisons.
    """
    ids = len(re.findall(r"#[\w-]+", sel))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]+\]", sel))
    return (ids, classes)


def _find_rule(html, pattern):
    m = re.search(r"^[ \t]*(" + pattern + r")[ \t]*\{([^}]*)\}", html, re.M)
    assert m, "no rule matching %r on the tab strip" % pattern
    return m.start(), m.group(1).strip(), m.group(2)


def test_the_chat_tint_really_does_lose_to_every_state_rule():
    html = HTML.read_text(encoding="utf-8")
    tint_at, tint_sel, tint_body = _find_rule(html, CHAT_RULE)

    assert "background:" in tint_body, "the chat tab sets no background of its own any more"
    # A third meaning needs a third hue: red already means "needs a human" on this strip and green
    # means "done", so reusing either would say something untrue about the tab.
    assert "var(--red" not in tint_body and "#e3f3e6" not in tint_body, (
        "the chat tint reuses a colour that already means something else on this strip: %r"
        % tint_body.strip())

    for pattern in STATE_RULES:
        at, sel, _body = _find_rule(html, pattern)
        tint_w, state_w = _weigh(tint_sel), _weigh(sel)
        # WEIGHT FIRST. This is the assertion the original test was missing, and the only one that
        # would have caught the id.
        assert tint_w <= state_w, (
            "the chat tint %r weighs %s but %r only weighs %s, so the tint wins outright and a "
            "chat tab in that state stops showing it" % (tint_sel, tint_w, sel, state_w))
        # Order decides only among equals.
        if tint_w == state_w:
            assert at > tint_at, (
                "%r ties the chat tint on weight but is declared BEFORE it, so the tint takes the "
                "tie and wins" % sel)


def test_the_accent_bar_is_not_what_carries_the_state():
    """The bar marks WHICH tab this is, not what state it is in, so it may outlive the state rules.

    Stated explicitly because it looks like an exception to the test above and is not: nothing else
    on the strip styles ::before, so there is no state rule for it to defeat. If a state rule ever
    starts painting ::before, this assertion is the thing that should start failing.
    """
    html = HTML.read_text(encoding="utf-8")
    before_rules = re.findall(r"^[ \t]*(\.dtabs [^{]*::before)[ \t]*\{", html, re.M)
    assert len(before_rules) == 1, (
        "more than one rule paints ::before on the tab strip, so they now compete and the chat "
        "bar's weight has to be compared like everything else: %r" % before_rules)
    assert "data-sec" in before_rules[0], before_rules[0]


def test_no_tab_on_the_strip_is_styled_by_id():
    """The general form of the bug, banned by shape so the next tab to get a colour cannot repeat it.

    An id in a tab-strip rule outweighs every state class on the strip, silently disabling them for
    that one tab. There is never a need for one here: every tab already carries data-sec, which
    weighs the same as a class and reads the same.
    """
    html = HTML.read_text(encoding="utf-8")
    offenders = re.findall(r"^[ \t]*(\.dtabs [^{]*#[\w-]+[^{]*)\{", html, re.M)
    assert not offenders, (
        "tab-strip rules targeted by id, which outweigh .needs / .is-done / [aria-selected] and "
        "disable them for that tab: %r. Use the data-sec attribute instead." % offenders)


def test_every_tab_the_strip_renders_can_be_reached_by_data_sec():
    """The tint hangs off data-sec, so a tab that lacks it would silently lose its colour.

    Cheap, and it pins the contract the CSS now depends on: `secTab` must keep emitting data-sec for
    every tab, not just for chat.
    """
    js = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "js" / "portal.js").read_text(
        encoding="utf-8")
    m = re.search(r"function secTab\(([^)]*)\)\s*\{(.{0,1600}?)\n  \}", js, re.S)
    assert m, "secTab is no longer shaped the way this test finds it"
    body = m.group(2)
    assert 'data-sec="' in body or "data-sec='" in body, (
        "secTab stopped emitting data-sec, which is what the chat tint now hangs off")
