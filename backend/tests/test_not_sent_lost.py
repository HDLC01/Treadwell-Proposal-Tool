"""The "close this bid lost" control on the drawer for a project nobody sent — EXECUTED.

Hanz, 2026-08-19: "Allow to mark a proposal as lost tho in the Created not sent category."

The store, the route and the synthesised row are covered in test_mark_unsent_lost.py. What is here
is the half a source read cannot see: that cancelling the dialog sends nothing, that the button
posts to the DRAFT endpoint, that the panel repaints past its own signature guard afterwards, and
that a failed save leaves the rep looking at a bid it has NOT claimed to close.

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
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip(), "the harness produced nothing — a dangling promise ends node silently"
    d = json.loads(r.stdout)
    assert "error" not in d, "%s\n%s" % (d.get("error"), d.get("stack", "")[:2000])
    return d


# ── the control is there, and only one half of it ────────────────────────────
@needs_node
def test_a_live_bid_is_offered_the_close(out):
    assert out["live"]["hasLost"], (
        "there is no way to close an unsent bid lost, which is the whole request")
    assert not out["live"]["hasReopen"], (
        "a live bid offers Reactivate, which reads as though it were already closed")
    # The heading, not only the button. Mutation-found gap: hardcoding it to "Closed lost" left
    # every test green while a live bid displayed "Closed lost" as a section heading directly above
    # a button offering to close it — which reads as a bid that is already dead.
    html = out["live"]["html"]
    assert "Not going ahead?" in html, (
        "the section heading does not ask the question; a live bid is being labelled as closed")
    assert "Closed lost</div>" not in html


@needs_node
def test_a_closed_bid_is_offered_the_reactivate_instead(out):
    """Both halves matter. A closed bid with no way back makes a mis-click permanent, and one
    still offering "Mark closed lost" says nothing happened."""
    assert out["lostPanel"]["hasReopen"], "a closed bid cannot be reopened"
    assert not out["lostPanel"]["hasLost"]
    assert "Another contractor" in out["lostPanel"]["html"], (
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
    does not know its own state — the same reason the follow-up cadence itself is now gated on a
    send that happened."""
    unsent = out["dialog"]["html"]
    assert "follow-ups stop" not in unsent, unsent[:400]
    assert "never sent" in unsent, "the dialog does not say what is actually true of this bid"
    assert "Lost tab" in unsent, "it does not say where the bid goes"
    assert "reactivate it later" in unsent, "it does not say the decision is reversible"
    # …and the sent wording still exists, so this is a branch rather than a deletion.
    assert "follow-ups stop" in out["dialogSent"]["html"]


# ── confirming ──────────────────────────────────────────────────────────────
@needs_node
def test_it_closes_the_bid_through_the_DRAFT_endpoint(out):
    """THE reason this feature needed writing at all: an unsent project has no portal_proposals
    row, so the portal's /status route has nothing to close. Posting there would 404 and the bid
    would stay on the board."""
    reqs = out["confirmed"]["requests"]
    assert len(reqs) == 1, "expected exactly one request, got %r" % reqs
    assert reqs[0]["path"] == "/api/draft/d-1/status", (
        "it posts to %s — the portal route has no row for an unsent project" % reqs[0]["path"])
    assert reqs[0]["method"] == "POST"
    assert reqs[0]["body"] == {"status": "closed_lost", "reason": "timing"}, (
        "the reason the rep picked is not what was sent: %r" % reqs[0]["body"])


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
    left holding the new state, both of which mutations 12 and 13 confirm it catches."""
    c = out["confirmed"]
    assert c["hasReopen"], "the drawer did not repaint — it still shows the pre-close panel"
    assert not c["hasLost"], "it still offers to close a bid it just closed"
    assert "Timing" in c["html"], "the redrawn panel does not name the reason"
    sig = c["sigAfter"]
    assert sig != "guard-me", "the guard still holds the pre-render signature"
    assert "closed_lost" in sig, (
        "the guard was re-armed with the OLD state, so the next 12s poll repaints it back to live")


@needs_node
def test_the_board_is_refreshed_too(out):
    """A closed bid has to leave the Created but not sent column and appear under Lost. The drawer
    repaint does not touch the board behind it."""
    assert out["confirmed"]["painted"] == ["board"]


@needs_node
def test_a_select_that_was_never_touched_still_sends_a_real_reason(out):
    """The `|| "other"` guard. A browser pre-selects the first option so this is belt-and-braces,
    but the route refuses an empty reason (test_mark_unsent_lost), so without it a rep who confirms
    without touching the dropdown would get an error instead of a closed bid."""
    reqs = out["defaultReason"]["requests"]
    assert len(reqs) == 1
    assert reqs[0]["body"]["reason"] == "other", reqs[0]["body"]


# ── reactivating ────────────────────────────────────────────────────────────
@needs_node
def test_reactivating_asks_nothing_and_sends_no_reason(out):
    """Putting a bid back needs no reason, and asking for one would be a dialog with nothing in it.
    A stale `reason` riding along would be stored by a route that only checks `status`."""
    reqs = out["reopened"]["requests"]
    assert len(reqs) == 1
    assert reqs[0]["body"] == {"status": "active"}, reqs[0]["body"]
    assert out["reopened"]["appended"] == 0, "reactivating opened a dialog"
    assert out["reopened"]["painted"] == ["board"], "the board still shows it under Lost"
    assert 'id="ns-lost"' in out["reopened"]["html"], (
        "the reopened panel does not offer to close it again")


# ── the failure path ────────────────────────────────────────────────────────
@needs_node
def test_a_failed_save_does_not_claim_the_bid_is_closed(out):
    """The optimistic repaint is the hazard in this design: the handler redraws from a row it
    patched itself, so on a failed write it would show a closed bid that no database agrees is
    closed — and the next 12s poll would silently flip it back."""
    f = out["failed"]
    assert f["requests"] == 1
    assert f["painted"] == 0, "it reloaded the board after a failed write"
    assert "Reactivate this bid" not in f["html"], (
        "the panel repainted as closed even though the write failed")
    assert "Mark closed lost" in f["html"], "the control is gone, so there is no way to retry"


@needs_node
def test_a_failed_save_says_what_happened_and_lets_them_retry(out):
    f = out["failed"]
    assert f["note"] and "postgrest down" in f["note"], (
        "the failure says %r, which does not tell the rep anything" % f["note"])
    assert f["btnDisabled"] is False, "the button is left disabled — the rep cannot try again"
    assert f["btnLabel"] == "Mark closed lost", (
        "the button still reads %r instead of going back to its label" % f["btnLabel"])
