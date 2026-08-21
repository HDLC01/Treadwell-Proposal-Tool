"""A HOLD ON A SENT BID: the way out, and the copy that stops attributing it to the customer.

Holds shipped on 2026-08-20 (Hanz, with Kyle's screenshot): two of the eight close-out answers,
"Project on Hold" and "Small Bid <$25k - Pending", leave the card on the Active board and pause the
reminder emails instead of killing the bid. The dialog says so in as many words:

    "<Project> stays on the Active board and the reminder emails pause for about 4 months. Nothing
     is sent to the customer. You can bring it back sooner."

On the UNSENT half that was all true. On the SENT half three things were wrong, all of them in the
last sentence:

  1. #fu-reopen rendered on isLost only. A held bid is not lost, so the estimator got the delay
     picker, Mark delayed and Mark closed lost, and no control that brought the bid back.
  2. The one obvious workaround failed too: the portal's followup-automation route called
     set_followup_enabled and never resume_followups, so turning automation "on" flipped a flag and
     left the cadence paused. (That half is asserted in the portal's own
     tests/test_crm_thread_cards.py, where the db calls are visible.)
  3. followupState said "The customer asked us to come back to this" about a hold a staff member
     pressed for internal reasons, and neither the reason nor the required comment appeared anywhere
     in the sent drawer.

EXECUTED, through backend/tests/js/drawer-render-harness.js, because none of this is visible in a
source read: a sent bid's hold is not on the proposal row at all. portal_proposals stores only the
pause DATE, so the reason and the comment live in portal_followups.detail, and what this panel says
depends on a payload rather than on a field. A source assertion would also not have caught the bug
being fixed here, which was a branch that was never entered.
"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent.parent / "frontend"
HARNESS = HERE / "js" / "drawer-render-harness.js"
PORTAL_JS = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@pytest.fixture(scope="module")
def hold():
    r = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                       capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip(), "the harness produced nothing — a dangling promise ends node silently"
    d = json.loads(r.stdout)
    assert "hold" not in d.get("errors", {}), (
        "%s\n%s" % (d["errors"]["hold"], d["errors"]["hold"][:2000]))
    return d["hold"]


def _lead(html):
    """The one sentence the follow-up panel leads with, as rendered."""
    m = re.search(r'<p class="note" id="fu-lead">(.*?)</p>', html, re.S)
    assert m, "the panel has no lead sentence at all"
    return m.group(1)


def _quote(html):
    """The quoted comment paragraph, or None when the panel drew none.

    Matched on the rendered ELEMENT rather than on the class name anywhere in the markup: the
    panel's own source comment explains the reused class by name, so a bare `"ns-why" in html`
    is true on every render and the absence half of these assertions was vacuous."""
    m = re.search(r'<p class="note ns-why">(.*?)</p>', html, re.S)
    return m.group(1) if m else None


# ── 1. there is a way out ────────────────────────────────────────────────────
@needs_node
def test_a_held_sent_bid_offers_a_bring_back(hold):
    """The dead end. Everything else in this file is about wording; this is the control that was
    missing, and its absence made the dialog's last sentence false."""
    html = hold["held"]["html"]
    assert 'id="fu-reopen"' in html, (
        "a held sent bid has no way back, so the four months cannot be ended early")
    assert "Bring this bid back" in html, (
        "the control is there under some other name; the unsent drawer calls this act "
        "Bring this bid back and one act should not have two names")


@needs_node
def test_the_dialog_and_the_drawer_now_agree(hold):
    """The disagreement stated as one assertion, because either half alone can be fixed by making
    the product worse: deleting the promise, or leaving the promise and the dead end."""
    assert "You can bring it back sooner" in PORTAL_JS, (
        "the close-out dialog no longer promises this; if that was deliberate, this test is the "
        "one to change, but the drawer must then stop offering a bring-back")
    assert 'id="fu-reopen"' in hold["held"]["html"], (
        "the dialog still promises the bid can be brought back sooner and the panel offers nothing")


@needs_node
def test_the_other_controls_survive_a_hold(hold):
    """Where the sent half deliberately differs from the unsent one, which hides the close-out on a
    held bid. There, nothing is chasing a bid nobody sent, so "bring it back, then close it out"
    costs nothing. Here, bringing a bid back RESUMES the cadence — so forcing that two-step on a job
    Kyle has just learned went to another GC would put an automated chase in front of the customer in
    between."""
    html = hold["held"]["html"]
    assert 'id="fu-lost"' in html, "a held bid cannot be closed out without resuming its chase first"
    assert 'id="fu-delay"' in html, (
        "a customer who rings mid-hold and asks for one month cannot be recorded")


# ── 2. pressing it clears the pause, through the route that can ──────────────
@needs_node
def test_the_bring_back_posts_the_one_status_that_clears_both_stores(hold):
    """`bring_back` on the DRAFT route, which clears our own marks and forwards `active` to the
    portal — and the portal's `active` branch is where db.resume_followups lives. That call is the
    whole of "the hold is off", and it is asserted where it is visible: the portal's
    test_crm_thread_cards.py::test_bringing_back_a_HELD_bid_clears_the_pause_and_closes_nothing.

    Posting the portal's own `/status` from here would look identical on screen and clear the pause
    too, but it would leave a by-hand won mark on our blob — which is the bug `bring_back` was added
    for. Posting `delayed` with fewer months, the other tempting shortcut, would not clear the pause
    at all, only shorten it."""
    r = hold["broughtBack"]
    assert r["pressed"], "the button was never rendered, so this proves nothing"
    assert len(r["requests"]) == 1, r["requests"]
    req = r["requests"][0]
    assert req["body"] == {"status": "bring_back"}, (
        "it posted %r, which does not clear a hold in one press" % (req["body"],))
    assert req["path"] == "/api/draft/held/status", (
        "it posts to %s; only the draft route clears our marks AND forwards active" % req["path"])


@needs_node
def test_it_asks_first_and_names_the_hold_as_the_thing_coming_off(hold):
    """The same prompt the other two bring-backs use, plus one sentence. An estimator who pressed
    Hold in August is looking for confirmation that THAT is what is being cleared, not a generic
    "are you sure"."""
    r = hold["broughtBack"]
    assert len(r["prompted"]) == 1, "a held bid was brought back with no prompt at all"
    assert r["prompted"][0]["name"] == "Nearman Creek", r["prompted"][0]
    assert r["prompted"][0]["extra"] == "That also lifts the hold.", (
        "the prompt says %r, so it does not name the hold" % r["prompted"][0]["extra"])


@needs_node
def test_saying_no_leaves_the_hold_alone(hold):
    """A confirm that acts either way teaches the estimator the dialog is noise."""
    r = hold["bringBackDeclined"]
    assert len(r["prompted"]) == 1, "the prompt was never shown"
    assert r["requests"] == [], "it brought the bid back anyway"


# ── the automation switch, which used to be the only thing to try ────────────
@needs_node
def test_the_switch_asks_before_it_lifts_a_pause(hold):
    """The endpoint now resumes as well as enabling, and that cuts both ways: the pause it lifts may
    be one the CUSTOMER asked for, and dropping that silently would start chasing somebody who told
    us not to. So the ask names the date being cleared."""
    asked = hold["toggleAccepted"]["asked"]
    assert len(asked) == 1, "turning automation on lifted a pause with no confirmation"
    a = asked[0]
    assert a["name"] == "Nearman Creek", a
    assert "2026-12-21" in a["detail"], (
        "the ask does not say what is being cleared: %r" % a["detail"])
    assert "reminders start again" in a["detail"], a["detail"]
    assert "not emailed" in a["detail"], (
        "it does not say whether pressing this sends the customer anything")
    assert len(hold["toggleAccepted"]["requests"]) == 1, (
        "saying yes sent nothing, so the switch is now unusable on a paused project")


@needs_node
def test_saying_no_to_that_changes_nothing(hold):
    r = hold["toggleDeclined"]
    assert len(r["asked"]) == 1, "the ask never happened"
    assert r["requests"] == [], "it switched automation on anyway, which lifts the pause"


@needs_node
def test_an_unpaused_project_is_still_one_click(hold):
    """The confirm is conditional for a reason: the ordinary case is a switch, and a dialog in front
    of every press is how a control gets clicked through without being read."""
    r = hold["toggleUnpaused"]
    assert r["asked"] == [], "the switch now interrupts a project that has no pause to lift"
    assert len(r["requests"]) == 1 and r["requests"][0]["body"] == {"enabled": True}, r["requests"]


# ── 3. the copy: who actually asked ─────────────────────────────────────────
@needs_node
def test_a_staff_hold_is_not_reported_as_something_the_customer_asked_for(hold):
    """The false statement. Every held sent bid read "The customer asked us to come back to this",
    which is a sentence about a conversation that never happened — the customer is deliberately
    never told about a hold. It is not a cosmetic wrong word either: who asked decides whether
    ringing them tomorrow is a follow-up or is news."""
    lead = _lead(hold["held"]["html"])
    assert "customer asked us" not in lead, (
        "a staff hold still reads as the customer's request: %r" % lead)
    assert "Somebody here put this on hold" in lead, (
        "the lead does not say who held it: %r" % lead)
    assert "was not told and is not being emailed" in lead, lead
    assert "2026-12-21" in lead, "the lead does not say when the chasing comes back: %r" % lead


@needs_node
def test_a_pause_the_customer_really_did_ask_for_still_reads_that_way(hold):
    """The other half, and the one that makes this a branch rather than a deletion. A plain "Mark
    delayed" IS the customer's timeline — the section it sits in says so ("Use these when a customer
    tells you by phone") — so that sentence has to survive."""
    plain = _lead(hold["plainPause"]["html"])
    assert "The customer asked us to come back to this" in plain, (
        "a plain delay lost the sentence that was right for it: %r" % plain)
    assert "Somebody here" not in plain, (
        "a pause with no reason on it is being reported as a staff hold: %r" % plain)
    assert hold["plainPause"]["pill"] == "Follow-up, Paused", hold["plainPause"]["pill"]


@needs_node
def test_the_customers_own_answer_replaces_an_older_hold(hold):
    """A held bid whose customer then rings and asks for one month is the CUSTOMER's pause from that
    moment: it is a newer answer about the same date. Reading the newest entry that happens to CARRY
    a reason instead would keep quoting a hold something later replaced, and the date on screen would
    be the customer's while the sentence was Kyle's."""
    lead = _lead(hold["customerAfterHold"]["html"])
    assert "The customer asked us to come back to this" in lead, lead
    assert "2026-09-21" in lead, "the resume date is not the customer's: %r" % lead
    assert "Project on Hold" not in lead, (
        "a superseded hold is still being quoted: %r" % lead)


@needs_node
def test_a_lapsed_hold_stops_claiming_the_bid_is_held(hold):
    """The log keeps every hold ever pressed. A bid held in April and running again since August must
    not still read "on hold" because the entry is in its history."""
    h = hold["lapsed"]
    assert h["pill"] == "Follow-up, On", h["pill"]
    assert "On hold" not in _lead(h["html"]), _lead(h["html"])
    assert _quote(h["html"]) is None, "the old hold's comment is still quoted on a live bid"


# ── the reason and the required comment, readable ───────────────────────────
@needs_node
def test_the_hold_reason_is_named_in_the_sent_drawer(hold):
    """It was write-only on this half: the dialog demanded an answer from Kyle's list and the sent
    drawer printed none of it, so "why is nothing being sent?" had no answer on the panel that
    stopped sending."""
    assert "On hold: Project on Hold" in _lead(hold["held"]["html"]), (
        "the panel does not say which of the two hold answers was picked")
    assert "Small Bid" in _lead(hold["heldSmall"]["html"]), (
        "the second hold answer is not named: %r" % _lead(hold["heldSmall"]["html"]))
    assert hold["heldSmall"]["pill"] == "Follow-up, On hold", hold["heldSmall"]["pill"]


@needs_node
def test_the_required_comment_is_printed_back_here_too(hold):
    """THE POINT OF REQUIRING IT. The comment is the tool's one mandatory free-text field, and the
    argument for making it mandatory was that a reason alone tells the next person nothing.

    ON THE FOLLOW-UP PANEL AND NOT ONLY IN THE THREAD, which reverses nsCloseNote's rule for this one
    case, deliberately. That rule ("a sent bid's comment goes into the customer thread ... so there
    is no second copy here") was written about a bid closed LOST: closing is an end, the thread card
    is the record, and nobody reopens the panel to read it. A hold is a live bid whose only remaining
    decision is bring-it-back-or-not, this panel is where that button is, and the comment is the
    input to that decision. Requiring a sentence and then filing it on a different tab from the
    control it informs is how a required field becomes paperwork."""
    quoted = _quote(hold["held"]["html"])
    assert quoted is not None, (
        "the comment somebody was forced to write is not readable on the panel it explains")
    assert "GC pushed the whole job to spring." in quoted, quoted


@needs_node
def test_the_printed_comment_cannot_carry_markup_out_of_the_textarea(hold):
    """It is free text typed by a person and it goes in as typed. `esc`, like everything else this
    drawer interpolates. Checked on the real rendered panel rather than on the helper, and against a
    comment that actually contains a tag — the ordinary fixture proves nothing about escaping."""
    quoted = _quote(hold["markupNote"]["html"])
    assert quoted is not None, "the panel drew no quote at all, so this proves nothing"
    assert "<b>" not in quoted, "the comment is interpolated raw: %r" % quoted
    assert "&lt;b&gt;" in quoted, quoted


@needs_node
def test_a_pause_with_no_comment_draws_no_empty_quote(hold):
    """Every pause set by "Mark delayed" has no comment at all, and there are real ones. An empty
    pair of quotation marks reads as somebody having written nothing on purpose."""
    assert _quote(hold["plainPause"]["html"]) is None
    assert _quote(hold["customerAfterHold"]["html"]) is None


# ── the board, which is the other half of what a hold promises ──────────────
@needs_node
def test_a_held_bid_still_sits_on_the_active_board(hold):
    """"Stays on the Active board" is the first clause of the dialog's promise, and the drawer cannot
    speak for it — so this is crm-core's own answer about the row, which is what the board renders
    from. A hold that set proposal_status would move the card to the Lost tab and take the pause with
    it."""
    b = hold["board"]
    assert b["isLost"] is False, "a held bid reads as lost, so it has left the Active board"
    assert b["isWon"] is False
    assert b["stage"] == "Sent", (
        "a held bid columns as %r rather than staying where it was" % b["stage"])
    assert b["pausedUntil"] == "2026-12-21", (
        "nothing pauses the chasing, so the reminders keep going during the hold")


@needs_node
def test_a_bid_held_and_then_genuinely_closed_lost_reads_as_lost(hold):
    """Lost beats everything in every reader (isLost is asked first), and a held bid that then dies
    keeps its pause date — so the two states coexist on one row and the order they are read in is
    the whole answer. Reading the hold first would leave a dead bid offering "you can bring it back
    sooner" and calling itself On hold on the tab strip."""
    h = hold["heldThenLost"]
    assert h["pill"] == "Follow-up, Closed lost", h["pill"]
    lead = _lead(h["html"])
    assert "moving forward" in lead and "went to different gc" in lead, lead
    assert "On hold" not in lead, "a closed bid still reads as on hold: %r" % lead
    assert "Reactivate this proposal" in h["html"], (
        "a closed bid does not offer the reactivate, or offers the hold's wording instead")
    assert "Bring this bid back" not in h["html"]
    assert 'id="fu-lost"' not in h["html"], "it still offers to close a bid it already closed"
    assert hold["boardAfterLost"] == {"isLost": True, "stage": "Closed lost"}, (
        hold["boardAfterLost"])


@needs_node
def test_a_held_bid_can_be_closed_out_without_being_woken_first(hold):
    """The reason Mark closed lost stays on a held panel. The two-step alternative resumes the
    cadence in between, which on a sent project means an automated chase going out to a customer
    whose job we have just been told we lost."""
    r = hold["closedFromHold"]
    assert len(r["requests"]) == 1, r["requests"]
    assert r["requests"][0]["body"]["status"] == "closed_lost", r["requests"][0]["body"]
    assert r["requests"][0]["path"] == "/api/portal/proposal/held/status", (
        "a sent bid's close must go to the portal route, which stops the cadence")


# ── house rules ─────────────────────────────────────────────────────────────
@needs_node
@pytest.mark.parametrize("case", ["held", "heldSmall", "plainPause", "customerAfterHold",
                                  "lapsed", "heldThenLost", "markupNote"])
def test_no_em_dash_in_the_new_copy(hold, case):
    """Same rule the other panels are held to, applied to the states this feature added. The
    Follow-up panel only, sliced out of the drawer: the Chat panel carries the portal's own
    "Heading — detail" system lines, which are inbound data rather than our words."""
    html = hold[case]["html"]
    panel = html[html.index('id="dpanel-followup"'):]
    assert "—" not in panel, "an em dash reached the follow-up panel of the %s drawer" % case
