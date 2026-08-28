"""The two buttons on a board card — EXECUTED.

Hanz, 2026-08-20: "the board card's two buttons become [Mark as closed] and [Lost]". Relabelled to
[Mark as won] and [Mark as lost] on 2026-08-22, as a matched pair - Hanz read the old labels and
asked whether the two were the same thing: it always posted the won mark, and "closed" beside a Lost button
reads as though it might mean either. Closed
MEANS WON. Files and Info sheet came off the card the same day, having already moved into both
drawers' Proposal tab.

THE FIRST BUTTON HAS TWO FACES SINCE 2026-08-28, and most of this file is now about that. Winning a
job used to take its card off this board onto a Won tab, which conflated two things: a won job still
owes a deposit and a set of contacts, and the sales meeting is run off the Active board. Hanz: "the
mark as won button would move the project the Won/Approved not into a separate pipeline", and "we
need to add a button on the Project container in the Active project named as 'Hand it off'". So
[Mark as won] became [Mark as won/approved] and moves the card into a COLUMN; what takes a card off
the board is a second, human press on [Hand it off], drawn in that same slot once the job is won.
There are still exactly two buttons on a live card - the first one just depends on the state.

Everything here is behavioural. "Mark as won/approved" has to reuse the existing by-hand won mark
rather than invent a third state; "Hand it off" has to post handed_off and to ASK rather than gate
when the contacts are not in; "Lost" has to pick its endpoint off `not_sent`, because a project the
customer has never seen has no portal_proposals row to close; all of them have to act on the project
whose name is on the card and on no other; and none may open the drawer over its own work, which is
a returns-from-a-branch property of one delegated listener and invisible to a source read.

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
def test_every_live_card_carries_one_forward_button_and_the_lost_one(out):
    """The whole ask, restated for 2026-08-28. This used to read "both buttons", by which it meant
    [Mark as won] on every live card. A won card now draws [Hand it off] in that same slot, so the
    invariant is no longer WHICH first button but that there is exactly ONE of them beside Mark as
    lost. Asserted as exclusivity rather than presence: a card offering both would be offering to
    win a job it has already won.

    Read back out of the rendered html per card, not from cardActions called on its own: the buttons
    are interpolated inside kanbanHtml's .map(), which is where the 2026-08-12 ReferenceError
    lived."""
    by = out["rendered"]["byCard"]
    assert by, "no cards rendered at all"
    for pid, has in by.items():
        assert has["won"] != has["handoff"], (
            "%s draws won=%s handoff=%s; a live card gets exactly one of the two"
            % (pid, has["won"], has["handoff"]))
        assert has["lost"], "%s has no Mark as lost button" % pid


@needs_node
def test_a_won_card_can_still_be_closed_lost(out):
    """New on 2026-08-28 and easy to lose: a won card stays on the board, so Mark as lost has to
    stay on it. A job can be won on the phone and then die, and the reason dialog is the only place
    that records why. Drop this button and the card cannot be closed at all without first undoing
    the win in the drawer, which is two screens away from where the news arrives."""
    by = out["rendered"]["byCard"]
    for pid in ("won-1", "won-received"):
        assert by[pid]["lost"], (
            "%s is won but offers no way to close it, so a job that dies after a verbal yes is "
            "stuck on the board" % pid)


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
def test_only_a_lost_or_a_handed_off_card_is_finished_and_offers_nothing(out):
    """"Decided" changed meaning on 2026-08-28, and this test changed with it. It used to mean lost
    OR won, because winning took the card off this board and left nothing to ask of it. A won card
    is back on the board now with real work still on it, so it is NOT finished - the two tests above
    assert it keeps a full pair of buttons. What IS finished is a lost bid and a job somebody has
    handed to operations, and on those a button would save and change nothing visible, which reads
    as broken. The way back for both is the drawer's bring-back, which needs a prompt naming the
    destination and cannot live on a 224px card.

    The Won tab this used to read is gone - it is the Handed Off tab now (TABS in portal.js), so
    that is the tab asserted here. Per card rather than over one long tab string, because a single
    leftover button on one branch is exactly what a whole-string check misses."""
    handed = out["rendered"]["handoffByCard"]
    assert handed, "the Handed Off tab drew no cards, so this proves nothing"
    for pid, has in handed.items():
        assert not has["handoff"], "%s offers to hand off a job operations already has" % pid
        assert not has["won"], "%s offers to mark a handed-off job won" % pid
        assert not has["lost"], (
            "%s offers Lost, which would close a job we won and handed over" % pid)
    lost = out["rendered"]["lostByCard"]
    assert lost, "the Lost tab drew no cards, so this proves nothing"
    for pid, has in lost.items():
        assert not has["lost"], "%s offers to lose it again" % pid
        assert not has["won"] and not has["handoff"], (
            "%s offers a forward button on a dead deal" % pid)


@needs_node
def test_the_table_view_has_no_card_buttons(out):
    """Kanban only, and deliberately: a row is seven columns of facts, and a control inside a table
    cell that also opens the drawer on click is a click nobody can aim. cardActions has exactly one
    call site, in kanbanHtml."""
    table = out["rendered"]["table"]
    assert "<table" in table, "the table view did not render, so this proves nothing"
    for marker in ("data-won=", "data-handoff=", "data-lost=", "deal-acts"):
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


# ── Mark as won ───────────────────────────────────────────────────────────
@needs_node
def test_the_won_button_posts_the_existing_won_mark(out):
    """The label has been [Mark as closed], [Mark as won] and — since 2026-08-28 — [Mark as
    won/approved], and the POST has never changed once. It is the same draft-side mark the drawer's
    own button makes, on the same route. A separate "closed" or "approved" state would be a second
    word for won that only the board could speak, and the Won/Approved column, the Won chip and the
    Notification Sending page would all have to learn it."""
    r = out["markWon"]
    assert len(r["requests"]) == 1, r["requests"]
    assert r["requests"][0]["path"] == "/api/draft/sent-1/status", r["requests"][0]["path"]
    assert r["requests"][0]["body"] == {"status": "won"}, (
        "it posts %r rather than the won mark that already exists" % r["requests"][0]["body"])
    assert r["asked"] == [], "marking a job won asked a question; the drawer's own does not either"


@needs_node
def test_marking_it_won_moves_the_card_without_waiting_for_the_poll(out):
    """WHERE it moves to changed on 2026-08-28 and the reason for the patch did not. The card used
    to be about to leave for the Won tab; it now crosses into the Won/Approved column and stays on
    this board, swapping its first button for Hand it off as it goes. Either way it moves out from
    under the cursor, and patching the board's own row means that happens on this paint instead of
    up to 25s later — the same thing the drawer does with its row."""
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


# ── Hand it off ──────────────────────────────────────────────────────────────
# Hanz, 2026-08-28: "We need to add a button on the Project container in the Active project named as
# 'Hand it off'." It replaced winning as the thing that takes a card off the board, and it is now
# the only thing that does, so every claim about it is made by pressing it.
@needs_node
def test_hand_it_off_is_offered_on_a_won_card_and_nowhere_else(out):
    """The three-way rule, in one place. A won card that nobody has handed off is the only card that
    gets this button: before the win there is nothing to hand over, and after the hand-off the press
    would save and change nothing visible, which reads as a broken control.

    "WON" HERE MEANS THE COLUMN, and until 2026-08-29 this test said otherwise — it listed
    `approved-1` among the cards that must NOT be offered a hand-off, on the reasoning that it "has
    not been won". The board disagreed: stage() files an approved job under Won/Approved whether or
    not the deposit has landed, so that card sat under a Won/Approved header offering to be marked
    won a second time, and could not be handed off at all. Three of them were on staging. The list
    below is now the right one; the invariant that would have caught the wrong one either way is
    asserted in test_the_column_and_the_first_button_never_disagree.

    Read per card off the real paints of the Active and Handed Off tabs, not off cardActions called
    on its own — the branch that picks between the two first buttons runs inside kanbanHtml's own
    .map()."""
    by = out["rendered"]["byCard"]
    for pid in ("won-1", "won-received", "approved-1"):
        assert by[pid]["handoff"], "%s is won but offers no way to hand it to operations" % pid
    for pid in ("ns-1", "sent-1"):
        assert not by[pid]["handoff"], (
            "%s has not been won, so handing it off would take a live bid off the board" % pid)
    handed = out["rendered"]["handoffByCard"]
    assert handed, "the Handed Off tab drew no cards, so the third case proves nothing"
    for pid, has in handed.items():
        assert not has["handoff"], "%s offers to hand off a job operations already has" % pid


@needs_node
def test_the_column_and_the_first_button_never_disagree(out):
    """THE INVARIANT, at the second attempt. A board card states two things six pixels apart — the
    column header says what happened, the first button offers what to do about it — and on
    2026-08-28 they shipped disagreeing.

    MY FIRST VERSION OF THIS TEST WAS ALSO WRONG, and Hanz found it in a screenshot of a real card
    rather than here. It asserted Hand it off appears if and only if the column is Won/Approved.
    But stage() tests the deposit and contacts branches BEFORE the won branch, so an approved card
    leaves that column the moment money moves: it is reachable in Deposit submitted, Deposit
    received and Contact info as well. The rule passed only because this harness contained none of
    those shapes. I had replaced a wrong hand-kept list with a wrong hand-reasoned rule.

    So it is stated over the stage ORDER, which is the thing that actually holds:

      · Won/Approved is reachable ONLY through wonOrApproved, so every card there offers the
        hand-off unconditionally. This is the direction that broke.
      · Created but not sent, Sent and Viewed all sit BELOW the won branch, so reaching one of them
        means wonOrApproved already answered no. No card there may offer a hand-off. This is the
        direction that keeps a live bid from being filed away.
      · The deposit and contacts columns are genuinely ambiguous and no rule keyed on their name can
        decide them — publishing a revision returns a card to 'sent' while leaving the money columns
        alone, so Deposit received holds both approved and unapproved cards. Those are checked
        against wonOrApproved itself, which is the question the button is supposed to be asking."""
    cols = out["rendered"]["columnOf"]
    by = out["rendered"]["byCard"]
    eligible = out["rendered"]["wonOrApproved"]
    assert cols, "the board paint yielded no columns, so this asserts nothing"

    BEFORE_THE_WON_BRANCH = {"Created but not sent", "Sent", "Viewed"}
    seen_won_col = seen_early = seen_ambiguous = False

    for pid, col in cols.items():
        if col == "Won/Approved":
            seen_won_col = True
            assert by[pid]["handoff"], (
                "%s sits under a Won/Approved header with no way to hand it off — the exact card "
                "Hanz screenshotted" % pid)
            assert not by[pid]["won"], (
                "%s offers to mark won a card its own column already calls Won/Approved" % pid)
        elif col in BEFORE_THE_WON_BRANCH:
            seen_early = True
            assert not by[pid]["handoff"], (
                "%s is in %s, a column only reachable when nobody has won it, yet it offers to "
                "hand a live bid to operations" % (pid, col))
            assert by[pid]["won"], "%s in %s offers no way to mark it won" % (pid, col)
        else:
            seen_ambiguous = True
            assert by[pid]["handoff"] == eligible[pid], (
                "%s is in %s: the column cannot say whether it was approved, and the button "
                "disagrees with wonOrApproved, which can" % (pid, col))
            assert by[pid]["won"] != eligible[pid], (
                "%s offers both buttons or neither" % pid)

    assert seen_won_col, "no card landed in Won/Approved, so the direction that broke is untested"
    assert seen_early, "no pre-win card on the board, so the safety direction is untested"
    assert seen_ambiguous, (
        "no approved card outside Won/Approved, so this is the same blind spot as the first version")
    assert any(eligible[p] for p in cols) and not all(eligible[p] for p in cols), (
        "every card is eligible or none is, so the invariant is trivially satisfied")


@needs_node
def test_hand_it_off_records_the_hand_off_on_the_draft(out):
    """Same route and same shape as the won mark, deliberately: `handed_off` is one more status on
    the draft's own status endpoint rather than a portal write. There is no portal equivalent to
    defer to — `proposal_status` is CHECK-constrained — and the press has to work on an unsent row,
    which has no portal_proposals row at all."""
    r = out["handoffAsked"]
    assert len(r["requests"]) == 1, r["requests"]
    assert r["requests"][0]["path"] == "/api/draft/won-1/status", r["requests"][0]["path"]
    assert r["requests"][0]["method"] == "POST"
    assert r["requests"][0]["body"] == {"status": "handed_off"}, (
        "it posts %r, which is not the hand-off the pipeline reads back as handed_off_at"
        % r["requests"][0]["body"])
    assert not [q for q in r["requests"] if "/api/portal/proposal/" in q["path"]], (
        "it also poked the portal's status route, which would close or reopen the proposal")


@needs_node
def test_it_asks_before_handing_off_a_job_whose_contacts_are_not_in(out):
    """IT ASKS RATHER THAN GATES, and that is the design decision. Hanz's phrasing was "once we
    receive the Contact Info, we indicate it as handed off", which describes the usual order rather
    than a rule — and a hard gate would make the button unreachable on the rows that need it most:
    a synthesised not-sent row (see _not_sent_rows) carries no contacts_status at all, so the gate
    could never open for a job won on the phone and never emailed. won-1 is exactly that row.

    The dialog is identified by its own confirm label, not merely counted, so this cannot pass on
    some other prompt having fired."""
    r = out["handoffAsked"]
    assert len(r["prompts"]) == 1, (
        "the contacts are not in and it handed off %s prompts deep" % len(r["prompts"]))
    assert r["prompts"][0]["confirmText"] == "Hand it off", r["prompts"][0]
    assert r["prompts"][0]["name"] == "Trabon Group", (
        "the prompt does not name the project it is about: %r" % r["prompts"][0].get("name"))


@needs_node
def test_it_does_not_ask_once_the_contacts_are_in(out):
    """The ordinary case, and the other half of the same decision: a dialog on the happy path is a
    click tax on every hand-off that followed the intended order. won-received carries
    contacts_status "received", which is the one value that skips the prompt — `!== "received"`
    rather than a falsy test, because an unsent row's undefined and a sent row's "requested" both
    mean nobody has confirmed they arrived."""
    r = out["handoffQuiet"]
    assert r["prompts"] == [], (
        "it stopped to ask about contacts that are already recorded: %r" % r["prompts"])
    assert len(r["requests"]) == 1 and r["requests"][0]["body"] == {"status": "handed_off"}, (
        r["requests"])


@needs_node
def test_answering_not_yet_leaves_the_card_exactly_where_it_was(out):
    """A prompt whose refusal still writes is worse than no prompt. Pressed on the SAME row that is
    handed off successfully in the test above, so this is not a row that was never going to move."""
    r = out["handoffRefused"]
    assert len(r["prompts"]) == 1, "it did not ask at all, so there was nothing to refuse"
    assert r["requests"] == [], "it handed the job off anyway after the prompt was refused"
    assert r["rendered"] == 0 and r["reloaded"] == 0
    assert out["handoffRefusedRow"]["handedOffAt"] is None, (
        "the board row was stamped handed off by a press somebody cancelled")


@needs_node
def test_the_hand_off_moves_the_card_off_the_board_without_waiting_for_the_poll(out):
    """This is the press that takes a card off the Active board, so the card is about to disappear
    from under the cursor. Patching the board's own row means that happens on this paint rather than
    up to 25s later — the same optimistic stamp the won mark and the drawer both use, and `load()`
    then replaces it with the server's."""
    assert out["handoffAskedRow"]["handedOffAt"], (
        "the board row was not patched, so the card sits on Active until the next poll")
    assert out["handoffAsked"]["rendered"] == 1, "the board was not repainted"
    assert out["handoffAsked"]["reloaded"] == 1, "the board was not re-read from the server"


@needs_node
def test_a_refused_hand_off_says_so_on_the_button_and_moves_nothing(out):
    """The optimistic patch is the hazard in this design, exactly as it is for the won mark: a card
    that vanishes off the board on a write the server refused is a job nobody chases again. The
    card has no note line under it, so the button itself has to carry the failure."""
    r = out["handoffFailed"]
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
@pytest.mark.parametrize("case", ["markWon", "handoffAsked", "handoffQuiet", "handoffRefused",
                                  "lostDismissed", "lostSent", "lostUnsent",
                                  "holdSent", "holdUnsent"])
def test_a_button_click_does_not_also_open_the_drawer(out, case):
    """Every button sits inside .deal, which is the drawer's own click target. Without an early
    return the click acts AND opens the drawer, and the drawer wins the repaint — so the button
    looks broken. Executed through the real delegated listener, because the property being tested
    is the order of its branches and whether each one returns.

    [data-handoff] joined the listener on 2026-08-28 as a THIRD branch ahead of the row, and
    handoffRefused is in this list for the case that branch is likeliest to get wrong: a press
    somebody cancelled still has to return rather than fall through to the drawer."""
    assert out[case]["openedDrawer"] == [], (
        "%s opened the drawer as well: %r" % (case, out[case]["openedDrawer"]))


@needs_node
def test_the_card_body_still_opens_the_drawer(out):
    """Which is what makes the nine assertions above mean something: the row branch is reachable,
    it is simply reached after the buttons."""
    assert out["plainCardClick"]["openedDrawer"] == ["sent-1"], out["plainCardClick"]
