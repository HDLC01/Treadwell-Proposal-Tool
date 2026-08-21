"""The two buttons on a board card — EXECUTED.

Hanz, 2026-08-20: "the board card's two buttons become [Mark as closed] and [Lost]", and Closed
MEANS WON. Files and Info sheet came off the card the same day, having already moved into both
drawers' Proposal tab.

Everything here is behavioural. "Mark as closed" has to reuse the existing by-hand won mark rather
than invent a third state; "Lost" has to pick its endpoint off `not_sent`, because a project the
customer has never seen has no portal_proposals row to close; both have to act on the project whose
name is on the card and on no other; and neither may open the drawer over its own work, which is a
returns-from-a-branch property of one delegated listener and invisible to a source read.

The 2026-08-12 outage was an unbound identifier inside kanbanHtml's own .map() with every source
assertion in this suite green.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FRONTEND = HERE.parent.parent / "frontend"
HARNESS = HERE / "js" / "card-actions-harness.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


@pytest.fixture(scope="module")
def out():
    r = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                       capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip(), "the harness produced nothing — a dangling promise ends node silently"
    d = json.loads(r.stdout)
    assert "error" not in d, "%s\n%s" % (d.get("error"), d.get("stack", "")[:2000])
    assert not d.get("errors"), json.dumps(d["errors"])[:2000]
    return d


# ── what the card draws ──────────────────────────────────────────────────────
@needs_node
def test_every_live_card_carries_both_buttons(out):
    """The whole ask. Read back out of the rendered html per card, not from cardActions called on
    its own: the buttons are interpolated inside kanbanHtml's .map(), which is where the 2026-08-12
    ReferenceError lived."""
    by = out["rendered"]["byCard"]
    assert by, "no cards rendered at all"
    for pid, has in by.items():
        assert has["won"], "%s has no Mark as closed button" % pid
        assert has["lost"], "%s has no Lost button" % pid


@needs_node
def test_files_and_info_sheet_are_gone_from_the_card(out):
    """They moved into BOTH drawers' Proposal tab on 2026-08-20 — the sent drawer's #go-files and
    #go-info, the not-sent drawer's [data-go-files] and [data-go-info], on the same URLs. So the
    card loses nothing by giving up the room. Asserted per card rather than over the whole board,
    because a single leftover button on one branch is exactly what a whole-string check misses."""
    for pid, has in out["rendered"]["byCard"].items():
        assert not has["files"], "%s still carries the old Files button" % pid
        assert not has["info"], "%s still carries the old Info sheet button" % pid


@needs_node
def test_a_card_that_is_already_decided_offers_nothing(out):
    """A lost card offering Lost and a won card offering Mark as closed are both controls that save
    and change nothing visible, which reads as broken. The way back for those two is the drawer's
    bring-back, which needs a prompt naming the destination and cannot live on a 224px card."""
    assert "data-won=" not in out["rendered"]["wonBoard"], (
        "the Won tab's cards offer to mark them won again")
    assert "data-lost=" not in out["rendered"]["wonBoard"], (
        "a won card offers Lost, which would close a job we won without asking anything")
    assert "data-won=" not in out["rendered"]["lostBoard"]
    assert "data-lost=" not in out["rendered"]["lostBoard"], (
        "the Lost tab's cards offer to lose them again")


@needs_node
def test_the_table_view_has_no_card_buttons(out):
    """Kanban only, and deliberately: a row is seven columns of facts, and a control inside a table
    cell that also opens the drawer on click is a click nobody can aim. cardActions has exactly one
    call site, in kanbanHtml."""
    table = out["rendered"]["table"]
    assert "<table" in table, "the table view did not render, so this proves nothing"
    for marker in ("data-won=", "data-lost=", "deal-acts"):
        assert marker not in table, "the table view grew %s" % marker


# ── the row a button belongs to ──────────────────────────────────────────────
@needs_node
def test_a_button_finds_its_own_project(out):
    """cardRowOf reads ALL rather than the filtered pool, because the 25s poll can move a row out
    of that pool between the paint and the click, and a button that silently does nothing is worse
    than one that acts on the project whose name is on the card."""
    assert out["lookup"]["found"], "a button cannot find the row it was drawn from"
    assert out["lookup"]["encoded"], (
        "the id is encoded into the attribute and not decoded on the way out, so any project id "
        "needing an escape resolves to nothing")
    # …and the reason that line is worth making. It read `encodeURIComponent("ns-1")` until
    # 2026-08-20, which encodes to itself, so dropping the decode left it green. The fixture id is
    # now one that genuinely changes shape, asserted here rather than assumed.
    assert out["lookup"]["encodedDiffers"] is True, (
        "the fixture id encodes to itself, so the assertion above cannot see a missing decode")
    assert out["lookup"]["missing"] is None, (
        "a row that has gone resolves to something, so the handler would act on a guess")


# ── Mark as closed ───────────────────────────────────────────────────────────
@needs_node
def test_mark_as_closed_posts_the_existing_won_mark(out):
    """"Closed" means WON — Hanz confirmed it. So this is the same draft-side mark the drawer's
    Mark won button makes, on the same route. A separate "closed" state would be a second word for
    won that only the board could speak, and the Won tab, the Won chip and the Notification Sending
    page would all have to learn it."""
    r = out["markWon"]
    assert len(r["requests"]) == 1, r["requests"]
    assert r["requests"][0]["path"] == "/api/draft/sent-1/status", r["requests"][0]["path"]
    assert r["requests"][0]["body"] == {"status": "won"}, (
        "it posts %r rather than the won mark that already exists" % r["requests"][0]["body"])
    assert r["asked"] == [], "marking a job won asked a question; the drawer's own does not either"


@needs_node
def test_marking_it_closed_moves_the_card_without_waiting_for_the_poll(out):
    """The card is about to leave for the Won tab. Patching the board's own row means it goes on
    this paint instead of up to 25s later, which is the same thing the drawer does with its row."""
    assert out["markWonRow"]["wonAt"], "the board row was not patched, so the card sits still"
    assert out["markWon"]["rendered"] == 1, "the board was not repainted"
    assert out["markWon"]["reloaded"] == 1, "the board was not re-read from the server"


@needs_node
def test_a_refused_write_says_so_on_the_button_and_moves_nothing(out):
    """The card is the one surface with no note line under it, so the button itself has to carry
    the failure — and the optimistic patch must not have happened."""
    r = out["markWonFailed"]
    assert r["rendered"] == 0 and r["reloaded"] == 0, "it repainted over a write that failed"
    assert "Failed" in r["label"] and "postgrest down" in r["label"], r["label"]
    assert r["disabled"] is False, "the button is left dead, so there is no way to retry"


# ── Lost ─────────────────────────────────────────────────────────────────────
@needs_node
def test_lost_asks_the_same_dialog_the_drawers_ask(out):
    """One close-out vocabulary, one required comment, one place to change either. The dialog is
    what collects them, so the card has to go through it rather than posting a bare reason."""
    r = out["lostDismissed"]
    assert len(r["asked"]) == 1, "the card closed a bid without asking anything"
    assert r["requests"] == [], "it posted anyway after the dialog was dismissed"
    assert r["rendered"] == 0 and r["reloaded"] == 0


@needs_node
def test_the_dialog_is_told_whether_the_customer_has_the_proposal(out):
    """It swaps one sentence on it. "All follow-ups stop" is the reassurance that matters on a
    proposal the customer has, and it is not true of a bid that was never sent."""
    assert out["lostUnsentOpts"]["opts"] == {"unsent": True}, out["lostUnsentOpts"]
    assert out["lostSent"]["asked"][0]["opts"] == {"unsent": False}, out["lostSent"]["asked"][0]


@needs_node
def test_a_sent_card_closes_through_the_portal_and_an_unsent_one_through_the_draft(out):
    """THE split this whole family of endpoints exists for. A sent project has a portal row whose
    close-lost also stops the cadence; an unsent one has no portal row at all, so posting there
    would 404 and the bid would stay on the board."""
    sent = out["lostSent"]["requests"]
    assert len(sent) == 1 and sent[0]["path"] == "/api/portal/proposal/sent-1/status", sent
    assert sent[0]["body"] == {"status": "closed_lost", "reason": "not_low_bid",
                              "note": "12% over Wilson."}, sent[0]["body"]
    unsent = out["lostUnsent"]["requests"]
    assert len(unsent) == 1 and unsent[0]["path"] == "/api/draft/ns-1/status", unsent
    assert unsent[0]["body"]["status"] == "closed_lost"


@needs_node
def test_a_hold_from_the_card_pauses_instead_of_closing_on_both_paths(out):
    """Hanz's two exceptions reach the card too, because it is the same dialog. A sent project's
    hold rides the portal's existing `delayed` status; an unsent one has no cadence to pause, so
    the draft records it and the board keeps the card where it is."""
    sent = out["holdSent"]["requests"]
    assert len(sent) == 1 and sent[0]["path"].startswith("/api/portal/proposal/"), sent
    assert sent[0]["body"]["status"] == "delayed", (
        "a hold on a sent card posted %r, so a live bid is filed as dead" % sent[0]["body"]["status"])
    assert sent[0]["body"]["reason"] == "on_hold" and sent[0]["body"]["note"]
    assert sent[0]["body"]["months"] >= 1
    unsent = out["holdUnsent"]["requests"]
    assert len(unsent) == 1 and unsent[0]["path"] == "/api/draft/ns-1/status", unsent
    assert unsent[0]["body"]["status"] == "on_hold", unsent[0]["body"]


@needs_node
def test_a_hold_does_not_move_the_card_optimistically(out):
    """The card stays exactly where it is, so there is nothing for an optimistic paint to hurry
    along — and the pause date belongs to the server, which is what returns it."""
    assert out["holdSent"]["rendered"] == 0, "a held card was repainted as though it had moved"
    assert out["holdUnsent"]["rendered"] == 0
    assert out["holdUnsent"]["reloaded"] == 1, "the board was never re-read, so the chip never draws"


# ── the drawer must not open over any of it ──────────────────────────────────
@needs_node
@pytest.mark.parametrize("case", ["markWon", "lostDismissed", "lostSent", "lostUnsent",
                                  "holdSent", "holdUnsent"])
def test_a_button_click_does_not_also_open_the_drawer(out, case):
    """Both buttons sit inside .deal, which is the drawer's own click target. Without an early
    return the click acts AND opens the drawer, and the drawer wins the repaint — so the button
    looks broken. Executed through the real delegated listener, because the property being tested
    is the order of its branches and whether each one returns."""
    assert out[case]["openedDrawer"] == [], (
        "%s opened the drawer as well: %r" % (case, out[case]["openedDrawer"]))


@needs_node
def test_the_card_body_still_opens_the_drawer(out):
    """Which is what makes the six assertions above mean something: the row branch is reachable,
    it is simply reached after the buttons."""
    assert out["plainCardClick"]["openedDrawer"] == ["sent-1"], out["plainCardClick"]
