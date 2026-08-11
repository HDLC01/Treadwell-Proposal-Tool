"""The board's "how they saw it" line, and the one thing it must never claim.

Half of Hanz's question — *"when a customer ... opens that chatbox with the specific project in
portal it is labeled as seen?"* — was already true: chat is the default view of the portal page,
and loading it marks the proposal viewed. The email half was invisible, so the portal records a
click on the per-proposal link and this line surfaces it.

RENAMED from `deliveryHint` to `seenLine` when the board moved to customer-journey columns. It is
no longer "did the email get through" bolted onto a Sent card; it is the detail behind the **Seen**
column, which exists precisely to hold the customers who have the proposal and have not answered.
So it now reports BOTH routes — portal or email — and only in that column, where the difference is
the whole question.

What it must be careful about: a portal view means a person definitely looked. An email link click
does not. That page serves before anyone signs in, and Outlook SafeLinks and mail scanners follow
links on their own. So the email wording never claims they saw it, the tooltip says so outright,
and the two routes are styled differently rather than identically.
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
def line(js):
    m = re.search(r"function seenLine\(p, colId\) \{(.*?)\n  \}", js, re.S)
    assert m, "seenLine() moved or was renamed"
    return m.group(1)


def test_the_line_is_rendered_on_the_card(js):
    assert "${seenLine(p, colId)}" in js, "the line is defined but never drawn"


def test_it_only_appears_in_the_seen_column(line):
    """In "Not opened" it would contradict the column. Past Seen — talking, approved, lost — the
    question is already answered and the line would compete with a stronger fact."""
    assert 'if (colId !== "seen") return "";' in line


def test_it_says_nothing_when_there_is_no_evidence(line):
    assert 'if (!how) return "";' in line


def test_it_reports_both_routes(line):
    """The Seen column holds customers reached either way, and which one changes what you do next:
    a portal view is worth a call; an email click with no portal view is worth checking the
    address."""
    assert "opened the portal" in line
    assert "email link opened" in line


def test_the_email_wording_never_claims_they_saw_it(line):
    """THE wording guarantee. A mail scanner following a link must not read on the board as the
    customer having looked at the bid.

    Checks the text the card actually EMITS. An earlier version searched the whole function and
    tripped over the word "viewed" inside a code comment — a test failing on its own documentation
    proves nothing about the product."""
    code = "\n".join(l for l in line.split("\n") if not l.strip().startswith("//"))
    code = re.sub(r'title="[^"]*"', "", code)             # the tooltips carry the caveats
    emitted = " ".join(re.findall(r"`([^`]*)`", code)).lower()
    assert emitted, "no template literal found; the labels may have moved"
    for word in ("seen by", "read it", "viewed the"):
        assert word not in emitted, "the label claims %r, which a click does not prove" % word


def test_the_email_tooltip_states_the_caveat_rather_than_hiding_it(line):
    """Somebody WILL read this as proof the customer saw the proposal. The card should say why it
    is not, in the place they look when they wonder."""
    tips = re.findall(r'title="([^"]*)"', line)
    assert tips, "no tooltip on the line"
    email_tip = " ".join(t for t in tips if "email" in t.lower()).lower()
    assert "not proof" in email_tip
    assert "scanner" in email_tip or "signs in" in email_tip


def test_the_portal_route_is_stated_plainly(line):
    """No hedging needed here — a portal view really is a person opening the proposal."""
    tips = re.findall(r'title="([^"]*)"', line)
    portal_tip = " ".join(t for t in tips if "portal" in t.lower()).lower()
    assert "opened the proposal" in portal_tip
    assert "not proof" not in portal_tip, "a portal view is a strong fact; do not hedge it"


def test_each_route_prefers_its_most_recent_timestamp(line):
    assert "p.last_viewed_at || p.viewed_at" in line
    assert "p.last_link_clicked_at || p.link_clicked_at" in line


def test_it_does_not_invent_a_status_or_move_the_card(line):
    """The line is a report. It must not touch the column, the cadence, or the drag rules."""
    for forbidden in ("proposal_status =", "canMove", "actionPlan", "fetch("):
        assert forbidden not in line, "seenLine does more than describe: %s" % forbidden


def test_the_styles_exist_and_distinguish_the_two_routes():
    css = HTML.read_text(encoding="utf-8")
    assert ".fu-seen {" in css, "no style for the line; it would inherit body text size"
    assert ".fu-seen.is-portal" in css and ".fu-seen.is-email" in css, (
        "both routes render identically, so the weaker signal looks as strong as the stronger one")
    rule = re.search(r"\.fu-seen \{([^}]*)\}", css)
    size = re.search(r"font-size:\s*([\d.]+)px", rule.group(1))
    assert size and float(size.group(1)) <= 11, (
        "the line should be quieter than the project name — it is context, not an action")


# ── the automation badge that replaced the Chasing/Paused columns ──────────────
def test_the_card_shows_what_we_are_doing_as_a_badge(js):
    """Chasing and Paused stopped being columns, so the card has to carry them — otherwise "are
    reminders going out for this one" became unanswerable from the board."""
    assert "${autoBadge(p, today)}" in js
    m = re.search(r"function autoBadge\(p, today\) \{(.*?)\n  \}", js, re.S)
    assert m, "autoBadge() is missing"
    badge = m.group(1)
    for label in ("Chasing", "Paused", "Not automated"):
        assert label in badge, "the badge cannot say %r" % label
    assert 'if (!a) return ""' in badge, (
        "a closed-lost proposal, or an approved one that has been paid, should show no badge — "
        "nothing is going out for those. An approved job with the deposit still out IS being "
        "chased and does get one; see test_followups_board_js.py, which owns that rule.")


def test_the_badge_styles_separate_the_three_states():
    css = HTML.read_text(encoding="utf-8")
    for cls in (".fu-auto.is-chasing", ".fu-auto.is-paused", ".fu-auto.is-off"):
        assert cls in css, "no style for %s" % cls
