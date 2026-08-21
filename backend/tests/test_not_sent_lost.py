"""The close-out control on the drawer for a project nobody sent — EXECUTED.

Hanz, 2026-08-19: "Allow to mark a proposal as lost tho in the Created not sent category."
Hanz, 2026-08-20, with Kyle's screenshot of his own eight reasons, and three decisions on top:

  · SIX of the eight close the job. "Project on Hold" and "Small Bid <$25k - Pending" do NOT —
    they put it on hold, which means the card STAYS on the Active board and the reminders pause.
  · The comment is REQUIRED. This is the first required free-text field in the tool; every other
    note here is optional and one of them carries a comment saying why.
  · Bringing a card back asks first, and the prompt names where the card is going.

The store, the route and the synthesised row are covered in test_mark_unsent_lost.py. What is here
is the half a source read cannot see: that the confirm button will not fire on an empty comment,
that each of Kyle's answers routes to the outcome he meant it to, that cancelling sends nothing,
that the panel repaints past its own signature guard, and that a failed save leaves the rep looking
at a bid it has NOT claimed to close.

Run for real because on 2026-08-12 an unbound identifier in portal.js took the Active Projects
board down on prod with every source assertion in this suite green.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent.parent / "frontend"
HARNESS = HERE / "js" / "not-sent-lost-harness.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@pytest.fixture(scope="module")
def out():
    r = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip(), "the harness produced nothing — a dangling promise ends node silently"
    d = json.loads(r.stdout)
    assert "error" not in d, "%s\n%s" % (d.get("error"), d.get("stack", "")[:2000])
    return d


# ── the control is there, and only one half of it ────────────────────────────
@needs_node
def test_a_live_bid_is_offered_the_close(out):
    assert out["live"]["hasLost"], (
        "there is no way to close an unsent bid out, which is the whole request")
    assert not out["live"]["hasReopen"], (
        "a live bid offers the bring-back, which reads as though it were already closed")
    # The heading, not only the button. Mutation-found gap: hardcoding it to "Closed lost" left
    # every test green while a live bid displayed "Closed lost" as a section heading directly above
    # a button offering to close it — which reads as a bid that is already dead.
    html = out["live"]["html"]
    assert "Not going ahead?" in html, (
        "the section heading does not ask the question; a live bid is being labelled as closed")
    assert "Closed lost</div>" not in html
    assert "On hold</div>" not in html, "a live bid is being labelled as on hold"


@needs_node
def test_a_closed_bid_is_offered_the_bring_back_instead(out):
    """Both halves matter. A closed bid with no way back makes a mis-click permanent, and one
    still offering to close it says nothing happened."""
    assert out["lostPanel"]["hasReopen"], "a closed bid cannot be brought back"
    assert not out["lostPanel"]["hasLost"]
    assert "Went to Different GC" in out["lostPanel"]["html"], (
        "the panel does not say WHY it was lost, so the reason is write-only")


# ── nothing is sent until somebody says yes ─────────────────────────────────
@needs_node
@pytest.mark.parametrize("how", ["cancel", "escape", "backdrop"])
def test_dismissing_the_dialog_closes_no_bid(out, how):
    """Three ways out, and all three have to be free. This is a destructive, board-visible action
    reached by one click, and Escape is how people leave a dialog they opened by accident."""
    r = out["dismiss_" + how]
    assert r["opened"], "the dialog never opened, so this proves nothing about dismissing it"
    assert r["requests"] == 0, "%s closed the bid anyway" % how
    assert r["removed"] >= 1, "the dialog is still on screen after %s" % how
    assert r["disabled"] is False, (
        "the button is left disabled, so a rep who cancels can never try again")


@needs_node
def test_the_dialog_does_not_promise_to_stop_something_that_is_not_running(out):
    """The sent version says "all follow-ups stop", which is the reassurance that matters there.
    Nothing is chasing a bid that was never sent, and promising to stop it reads as a system that
    does not know its own state — the same reason the follow-up cadence itself is gated on a send
    that happened."""
    unsent = out["dialog"]["sub"]
    assert "follow-ups stop" not in unsent, unsent
    assert "never sent" in unsent, "the dialog does not say what is actually true of this bid"
    assert "Lost tab" in unsent, "it does not say where the bid goes"
    assert "bring it back later" in unsent, "it does not say the decision is reversible"
    # …and the sent wording still exists, so this is a branch rather than a deletion.
    assert "follow-ups stop" in out["dialogSent"]["sub"]


# ── THE REQUIRED COMMENT ────────────────────────────────────────────────────
@needs_node
def test_the_confirm_button_starts_disabled_with_the_reason_wanted_said_out_loud(out):
    """The house idiom for a must-fill field, borrowed off the estimator picker: the button starts
    disabled and a sibling note says what is wanted. A disabled button with no explanation beside
    it is a control that reads as broken."""
    d = out["dialog"]
    assert d["goDisabledOnOpen"] is True, (
        "the confirm button is live on an empty comment, so the first thing the route does is 422")
    assert d["errOnOpen"], "nothing on screen says why the button will not press"
    assert "Say what happened" in d["errOnOpen"], d["errOnOpen"]


@needs_node
def test_an_empty_comment_sends_nothing_and_leaves_the_dialog_open(out):
    """The whole of the new precedent. A reason on its own tells the next person nothing: by the
    end of a quarter "Not Low Bid" is eight identical cards. So the field is refused empty — and
    refused HERE, in front of the estimator, rather than by a 422 they have to decode."""
    e = out["emptyNote"]
    assert e["opened"], "the dialog never opened"
    assert e["requests"] == 0, "it closed the bid with no comment on it"
    assert e["painted"] == 0, "it reloaded the board over a write it never made"
    assert e["goDisabledAfterTyping"] is True, (
        "the button became live after an empty input event, so the guard only ran once")
    assert e["stillOnScreen"], (
        "the dialog closed itself on a refused confirm, so the typed reason is lost and the rep "
        "has to start again")


@needs_node
def test_whitespace_is_not_a_comment(out):
    """A required field that accepts a space is decoration. Space is also exactly what somebody
    does to get past one, so this is the realistic attempt rather than an adversarial one."""
    b = out["blankNote"]
    assert b["requests"] == 0, "three spaces counted as saying what happened"
    assert b["goDisabled"] is True
    assert b["err"], "and it does not say why"


@needs_node
def test_the_comment_travels_with_the_reason(out):
    """Storing it is drafts.set_close_lost's job; getting it there is this one's. A dialog that
    collects a required field and then drops it on the floor is the worst of both."""
    body = out["byReason"]["not_low_bid"]["requests"][0]["body"]
    assert body["note"] == "Said so on the phone.", body


# ── each of Kyle's eight answers, one at a time ──────────────────────────────
@needs_node
def test_the_dialog_offers_exactly_kyles_list(out):
    """Verbatim, and in his order. The dialog is built from C.CLOSE_CHOICES, so this is really an
    assertion about that array reaching the markup — but the LIST is the product decision, and a
    reason quietly dropped from it is a reason nobody can record again."""
    labels = [c["label"] for c in out["closeChoices"]]
    assert labels == ["Not Low Bid", "No Response", "Project to Rebid", "Project on Hold",
                      "Small Bid <$25k - Pending", "Went to Different GC",
                      "Unable to meet GC schedule", "Project Cancelled", "Other"], labels
    html = out["dialog"]["html"]
    for label in labels:
        # The markup escapes, so compare against the escaped form for the one that needs it.
        assert label.replace("<", "&lt;") in html, "%r is not offered in the dialog" % label


@needs_node
@pytest.mark.parametrize("reason", ["not_low_bid", "no_response", "to_rebid", "different_gc",
                                    "gc_schedule", "canceled", "other"])
def test_the_six_that_close_it_post_closed_lost(out, reason):
    """Hanz's decision, one row per answer. `other` is not on Kyle's screenshot and rides along
    because the dialog falls back to it when the select has no value at all."""
    r = out["byReason"][reason]
    assert r["outcome"] == "lost", "%s is declared as %s in crm-core" % (reason, r["outcome"])
    assert len(r["requests"]) == 1, r["requests"]
    body = r["requests"][0]["body"]
    assert body["status"] == "closed_lost", (
        "%s posted %r, so a lost bid is not being recorded as lost" % (reason, body["status"]))
    assert body["reason"] == reason
    assert r["requests"][0]["path"] == "/api/draft/d-1/status", (
        "it posts to %s — the portal route has no row for an unsent project"
        % r["requests"][0]["path"])
    assert r["goLabel"] == "Close it out", (
        "the button says %r, which does not describe closing a bid" % r["goLabel"])
    assert "Lost tab" in r["sub"], r["sub"]


@needs_node
@pytest.mark.parametrize("reason", ["on_hold", "small_bid_pending"])
def test_the_two_that_do_not_close_it_post_a_hold(out, reason):
    """The decision that is easiest to get wrong, because the control is the same one. Hanz,
    2026-08-20: these two "put it on hold, meaning the card STAYS on the Active board and the
    reminder emails PAUSE"."""
    r = out["byReason"][reason]
    assert r["outcome"] == "hold", "%s is declared as %s in crm-core" % (reason, r["outcome"])
    assert len(r["requests"]) == 1, r["requests"]
    body = r["requests"][0]["body"]
    assert body["status"] == "on_hold", (
        "%s posted %r — a bid nobody has lost is being filed as lost" % (reason, body["status"]))
    assert body["reason"] == reason and body["note"]
    assert r["goLabel"] == "Put it on hold", (
        "the button says %r on a hold, which promises the wrong thing" % r["goLabel"])
    assert "stays on the Active board" in r["sub"], r["sub"]
    assert "Lost tab" not in r["sub"], "the copy still sends it to the Lost tab: %r" % r["sub"]


@needs_node
@pytest.mark.parametrize("reason", ["on_hold", "small_bid_pending"])
def test_a_held_bid_does_not_repaint_as_closed_lost(out, reason):
    """The optimistic patch is where this would go wrong: reusing the closed-lost patch would show
    the rep a bid filed as dead for the twelve seconds until the board caught up, and then flip."""
    html = out["byReason"][reason]["html"]
    assert "On hold</div>" in html, "the panel does not say the bid is on hold"
    assert "Closed lost</div>" not in html, "the panel repainted a held bid as closed lost"
    assert 'id="ns-reopen"' in html, "a held bid has no way back"


@needs_node
def test_the_hold_pause_is_the_number_the_backend_uses(out):
    """One feature, one pause length. Read out of portal.js by the harness and compared against
    main.py here, so the sent half and the unsent half cannot come to pause for different lengths
    of time — which nothing on screen would explain."""
    import main
    assert out["holdMonths"] == main.HOLD_PAUSE_MONTHS, (
        "the browser sends months=%s and the backend holds for %s"
        % (out["holdMonths"], main.HOLD_PAUSE_MONTHS))


@needs_node
def test_the_hold_answers_are_not_lost_tab_columns(out):
    """LOST_COLS is derived from LOST_REASON, so a hold reason living in that map would put a
    column of live bids on the tab of dead ones."""
    for key in out["holdReasons"]:
        assert key not in out["lostReasons"], (
            "%s is both a hold and a lost reason, so a held bid gets a Lost column" % key)


# ── confirming ──────────────────────────────────────────────────────────────
@needs_node
def test_the_panel_shows_the_decision_it_just_made(out):
    """The drawer has to redraw from the patched row, or the rep is left looking at a panel still
    offering to close a bid that is already closed and presses it again.

    On the `DRAWER_SIG = ""` line in that handler, honestly: mutation testing says removing it
    changes nothing here, and that is correct rather than a hole in this test. The guard only
    suppresses a repaint when the signature is IDENTICAL, and the optimistic patch adds
    proposal_status and followup_state — so the new signature always differs and the redraw goes
    through either way. The line is defensive, matching wireNotSentAssign beside it, and this test
    does not pretend to pin it. What it does pin is that the redraw HAPPENS and that the guard is
    left holding the new state."""
    c = out["byReason"]["gc_schedule"]
    assert 'id="ns-reopen"' in c["html"], (
        "the drawer did not repaint — it still shows the pre-close panel")
    assert 'id="ns-lost"' not in c["html"], "it still offers to close a bid it just closed"
    assert "Unable to meet GC schedule" in c["html"], "the redrawn panel does not name the reason"
    assert "closed_lost" in c["sigAfter"], (
        "the guard was re-armed with the OLD state, so the next 12s poll repaints it back to live")


@needs_node
def test_the_board_is_refreshed_too(out):
    """A closed bid has to leave the Created but not sent column and appear under Lost. The drawer
    repaint does not touch the board behind it."""
    assert out["byReason"]["not_low_bid"]["painted"] == ["board"]


@needs_node
def test_a_select_that_was_never_touched_still_sends_a_real_reason(out):
    """The `|| "other"` guard. A browser pre-selects the first option so this is belt-and-braces,
    but the route refuses an unknown reason (test_mark_unsent_lost), so without it a rep who
    confirms without touching the dropdown would get an error instead of a closed bid."""
    reqs = out["defaultReason"]["requests"]
    assert len(reqs) == 1
    assert reqs[0]["body"]["reason"] == "other", reqs[0]["body"]


# ── bringing it back ────────────────────────────────────────────────────────
@needs_node
def test_bringing_a_bid_back_asks_first_and_names_the_destination(out):
    """Hanz, 2026-08-20: "before they do that there should be a prompt saying are they sure". A
    prompt that only asks "are you sure?" cannot be answered — sure of WHAT? — so the destination
    is computed by running the board's own stage() over the row with the outcome cleared."""
    r = out["reopened"]
    assert r["present"], "there is no way back"
    assert len(r["prompts"]) == 1, "the bid was brought back with no prompt at all"
    ask = r["prompts"][0]
    assert ask["name"] == "Nearman Creek", "the prompt does not name the project: %r" % ask
    assert "back under Created but not sent" in ask["after"], (
        "the prompt does not say where the card is going: %r" % ask["after"])
    assert "reminders start again" in ask["detail"], ask["detail"]


@needs_node
def test_saying_no_to_the_prompt_changes_nothing(out):
    """A confirm that acts either way is worse than no confirm: it teaches the estimator that the
    dialog is noise."""
    r = out["reopenDeclined"]
    assert len(r["prompts"]) == 1, "the prompt was never shown"
    assert r["requests"] == [], "it brought the bid back anyway"
    assert r["painted"] == [], "and reloaded the board over a write it never made"


@needs_node
def test_the_bring_back_clears_every_mark_in_one_press(out):
    """`bring_back`, not `active`. A bid marked won and then closed lost reads as Lost only, so
    clearing one mark drops the card onto the Won tab instead of back on the board — which is the
    case Hanz named: "if projects are both won and lost"."""
    assert out["wonThenLost"]["readsAsLost"] is True
    assert out["wonThenLost"]["readsAsWon"] is True, (
        "the fixture is not actually both, so this test proves nothing")
    assert out["wonThenLost"]["stage"] == "Closed lost", (
        "lost no longer beats won, which is a change of rule this test does not cover")
    reqs = out["wonThenLostReopened"]["requests"]
    assert len(reqs) == 1, reqs
    assert reqs[0]["body"] == {"status": "bring_back"}, (
        "it posted %r, which clears one mark and leaves the other" % reqs[0]["body"])


@needs_node
def test_the_prompt_for_a_won_and_lost_bid_names_the_column_the_timestamps_earn(out):
    """Not "Won". Clearing the by-hand mark is part of the same press, so promising the Won tab
    would send the estimator looking for the card on the wrong board."""
    dest = out["wonThenLost"]["destination"]
    assert dest == "Created but not sent", (
        "the prompt promises %r for a bid that was never sent" % dest)


@needs_node
def test_a_bid_on_hold_stays_on_the_active_board_and_can_be_woken(out):
    """The whole point of routing two of Kyle's answers away from closed_lost."""
    h = out["heldPanel"]
    assert h["isLost"] is False, "a held bid reads as lost, so it left the Active board"
    assert h["stage"] == "Created but not sent", (
        "a held bid columns as %r rather than staying where it was" % h["stage"])
    assert h["pausedUntil"], "nothing pauses the chasing, so the reminders keep going"
    assert h["hasReopen"] and not h["hasLost"]
    assert "on hold" in h["html"], "the panel does not say the bid is on hold"
    reqs = out["heldReopened"]["requests"]
    assert len(reqs) == 1 and reqs[0]["body"] == {"status": "bring_back"}, reqs
    assert len(out["heldReopened"]["prompts"]) == 1, "waking a held bid asked nothing"


@needs_node
def test_the_destination_is_the_furthest_step_the_card_actually_reached(out):
    """The reason no "previous stage" field exists. Closing a job lost never overwrote a pipeline
    timestamp, so the answer is derivable — and derived, it stays right when a deposit lands while
    the job sits closed.

    `viewed` answers "Sent" ON PURPOSE and matches the portal: db.reopen_if_closed deliberately
    restores a previously-viewed row as 'sent' because "reopening is a fresh chase", and
    cycle_viewed_at is what picks the reminder track. Promising "Viewed" here would be this file
    disagreeing with the write it is describing."""
    d = out["destinations"]
    assert d["unsent"] == "Created but not sent"
    assert d["sent"] == "Sent"
    assert d["viewed"] == "Sent", (
        "this says %r; the portal restores a viewed row as sent, so the prompt would lie" % d["viewed"])
    assert d["approved"] == "Approved", (
        "an approved job is promised %r — the approval survives close_lost and reopen_if_closed "
        "restores it, so anything else throws away a win" % d["approved"])
    # Money in and contacts in are WON by the numbers, and clearing a by-hand mark cannot undo
    # that, so the honest answer names the Won tab rather than an Active column.
    assert d["depositIn"].startswith("Won"), d["depositIn"]
    assert d["contactsIn"] == "Won · Complete", d["contactsIn"]


# ── the failure path ────────────────────────────────────────────────────────
@needs_node
def test_a_failed_save_does_not_claim_the_bid_is_closed(out):
    """The optimistic repaint is the hazard in this design: the handler redraws from a row it
    patched itself, so on a failed write it would show a closed bid that no database agrees is
    closed — and the next 12s poll would silently flip it back."""
    f = out["failed"]
    assert f["requests"] == 1
    assert f["painted"] == 0, "it reloaded the board after a failed write"
    assert "Bring this bid back" not in f["html"], (
        "the panel repainted as closed even though the write failed")
    assert "Close this bid out" in f["html"], "the control is gone, so there is no way to retry"


@needs_node
def test_a_failed_save_says_what_happened_and_lets_them_retry(out):
    f = out["failed"]
    assert f["note"] and "postgrest down" in f["note"], (
        "the failure says %r, which does not tell the rep anything" % f["note"])
    assert f["btnDisabled"] is False, "the button is left disabled — the rep cannot try again"
    assert f["btnLabel"] == "Close this bid out", (
        "the button still reads %r instead of going back to its label" % f["btnLabel"])


@needs_node
@pytest.mark.parametrize("evt", ["input", "change"])
def test_each_event_that_re_checks_the_comment_works_on_its_own(out, evt):
    """The house idiom for a required field listens for BOTH, and the two failures are different.

    `input` alone missing leaves the button dead until the box loses focus, which reads as broken
    while you are still typing in it. `change` alone missing misses a paste from the context menu,
    which some browsers report only as `change`. Driven one event at a time on purpose: the other
    cases in this file fire both, and firing both means dropping either listener passes."""
    r = out["byTypingEvent"][evt]
    assert r["goDisabled"] is False, (
        "after typing with `%s` alone the confirm button is still dead, so the estimator cannot "
        "close the bid without doing something else first" % evt)
    assert r["err"] == "", "the required-field line still asks for a comment that is there"
    assert r["requests"] == 1 and r["body"]["note"] == "GC went with Wilson.", r


# ── the won mark's own undo, which also moves the card now ───────────────────
@needs_node
def test_taking_a_by_hand_won_mark_off_asks_first_and_names_where_it_lands(out):
    """wireWon's comment said for a day that NEITHER half of the won mark had a prompt, and gave a
    good reason: nothing is sent, nothing leaves the pipeline. That held while a won card stayed
    among the live ones. It stopped holding on 2026-08-20, when the Won TAB took won jobs off the
    Active board — undoing the mark MOVES the card now, to whichever Active column its own stamps
    earn — and Hanz asked for the prompt in the same breath as the bring-back: "before they do that
    there should be a prompt saying are they sure"."""
    panel = out["wonByHandPanel"]
    assert panel["hasUndo"] and not panel["hasMark"], panel
    r = out["wonUndone"]
    assert r["present"], "a bid marked won by hand offers no way back"
    assert len(r["prompts"]) == 1, "the mark came off with no prompt at all"
    ask = r["prompts"][0]
    assert ask["name"] == "Nearman Creek", ask
    assert "back under Created but not sent" in ask["after"], (
        "the prompt does not say where the card is going: %r" % ask["after"])
    assert len(r["requests"]) == 1, r["requests"]
    assert r["requests"][0]["body"] == {"status": "not_won"}, (
        "it posted %r; `bring_back` here would also forward `active` to the portal and resume a "
        "cadence somebody may have paused on purpose" % r["requests"][0]["body"])


@needs_node
def test_saying_no_leaves_the_won_mark_on(out):
    r = out["wonUndoDeclined"]
    assert len(r["prompts"]) == 1, "the prompt was never shown"
    assert r["requests"] == [], "it cleared the mark anyway"


# ── the comment, printed back ────────────────────────────────────────────────
@needs_node
def test_the_comment_is_printed_back_in_the_drawer(out):
    """The point of requiring it. It is the tool's one mandatory free-text field, and the argument
    for making it mandatory was that a reason on its own tells the next person nothing — so a
    comment that is validated, stored and then never shown anywhere would cost the estimator a
    sentence and give the next reader nothing.

    THE DRAWER AND NOT THE CARD: a card is 224px wide and this is a paragraph. Both closed-lost and
    on-hold, because both branches asked for one."""
    assert "12% over Wilson" in out["notePrinted"]["lost"], (
        "a closed bid's drawer does not say what happened")
    assert "GC has gone quiet." in out["notePrinted"]["held"], (
        "a held bid's drawer does not say why it is on hold")


@needs_node
def test_the_printed_comment_cannot_carry_markup_out_of_the_textarea(out):
    """It is the only free text on this panel and it goes in as typed. `esc`, like everything else
    the drawer interpolates."""
    assert "<b>" not in out["notePrinted"]["lost"], "the comment is interpolated raw"
    assert "&lt;b&gt;" in out["notePrinted"]["lost"], out["notePrinted"]["lost"][:200]


@needs_node
def test_a_bid_closed_before_the_comment_existed_shows_no_empty_quote(out):
    """Every bid closed before 2026-08-20 has a reason and no comment, and there are real ones. An
    empty pair of quotation marks would read as though somebody had written nothing on purpose."""
    html = out["notePrinted"]["lostNoNote"]
    assert "ns-why" not in html, "an empty quote is drawn for a bid that never had a comment"
    assert "closed lost" in html, "the panel did not render at all, so this proves nothing"
