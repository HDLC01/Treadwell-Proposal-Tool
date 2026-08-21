"""The Won tab: where a won job lives, and why its columns are what is outstanding.

THE BUG. Hanz, 2026-08-20:

    "I marked Trabon Group project as Won but it's still in the Created but Not Sent bucket."

And, in the same breath: "Even for created not sent we must be able to mark it as won or lost."

Everything worked except the only part he could see. `won_at` reaches the browser for a never-sent
project (drafts.py names it in the fast projection, main.py copies it onto the synthesised not-sent
row), isWon reads it, and the card grew a Won chip on 2026-08-19 — but crm-core's stage() never
consulted won state at any position, so the card stayed in the column its stage put it in. A card that
says "Won" while sitting in the bucket for bids nobody has sent is worse than one that says nothing:
the estimator reads the bucket.

THE DECISION, AND THE REVERSAL IT IS. Hanz chose a WON TAB that takes every won job, off the Active
board entirely, the way Lost comes off it. That reverses the reasoning recorded here and in
portal.js's chipsHtml one day earlier, which kept won cards on the live board because a won job still
has work on it — its "Deposit received" and "Contact info" columns are both live, and moving the card
would hide real work from the people doing it. That argument was right about the risk and wrong about
the fix.

WHAT MAKES THE MOVE SAFE is the mitigation, and it is the same one the Lost tab uses: the tab has its
OWN columns, and they are what is still OUTSTANDING rather than how far along the pipeline the job got.

    Won before approval   the customer has not agreed in the portal — unsent, or sent and not yet
                          approved — so nothing downstream of approval has been asked for
    Deposit outstanding   approved, and the money question is not settled
    Contacts outstanding  approved, money settled, the customer has not sent the project contacts
    Complete              nothing outstanding

Grouping that tab by stage would give one tall column and answer nothing, exactly as it would on Lost.

THE FIRST COLUMN READ "Won before sending" AND TESTED `not_sent` ALONE for a few hours on 2026-08-20,
and that was wrong for the one case the by-hand mark exists for. A verbal yes on a proposal that IS out
— sent, unapproved, never invoiced — went to "Deposit outstanding", telling whoever chases money that
money was owed on a job nobody has asked a customer for. drafts.set_won was built for precisely that
shape ("days before the customer clicks Approve"), and lost-tab-harness.js has fixtured it as
`won-marked` since the day before. The column is now what the portal itself gates on: no deposit and no
contacts question exists until the customer approves, so an unapproved win names neither.

THE FOUR POOLS PARTITION `ALL`, and that property is worth more than any single assertion here: it is
what makes the four pills add up, and what guarantees no proposal is reachable from no tab. The
precedence is lost, then test, then won — a won-then-cancelled job is Lost only (crm-core's isWon
records that every reader asks isLost first), and a TEST project that was won stays under Test, because
scratch work does not become real work by being marked won.

WHAT THE MOVE DID NOT DO is strand a column on the live board, and that is worth proving here because
it is the objection to the whole design. An adversarial review read the four pools and concluded that
three of the Active board's seven columns were now unreachable forever. They are not: its argument
needs approval to be permanent and approval is not permanent. db.reset_for_revision NULLS approved_at
when a new revision is published and deliberately leaves the deposit and contacts columns alone, so a
job whose money is already in can be waiting on an approval again — live work, not a win, and the most
valuable card on that board. All seven columns are fixtured and rendered below. Nothing here removes a
column; whether to remove one is Hanz's call, and this is the evidence for it.

EXECUTED, NOT GREPPED. Every claim about a pool, a column or a count runs the real portal.js function
through backend/tests/js/won-tab-harness.js. A source-text assertion let `ReferenceError: STAGE_CREATED
is not defined` take this board down on production on 2026-08-12 with every test green, and this change
adds a whole new column vocabulary to the same renderer.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "won-tab-harness.js"
# The drawer's own harness, borrowed rather than rebuilt. It already renders renderNotSent with the
# thirty-odd names that panel transitively needs bound the way portal.js binds them; a second lift of
# the same function here would be a second thing to keep in step with the page.
DRAWER_HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "drawer-render-harness.js"
CORE = FRONTEND / "js" / "crm-core.js"
PORTAL_JS = FRONTEND / "js" / "portal.js"
PORTAL_HTML_PATH = FRONTEND / "portal.html"
PORTAL_HTML = PORTAL_HTML_PATH.read_text(encoding="utf-8")

WON_EARLY = "Won before approval"
WON_DEPOSIT = "Deposit outstanding"
WON_CONTACTS = "Contacts outstanding"
WON_DONE = "Complete"

# The live board's seven, in order. Named here because one of this file's jobs is now to prove that
# taking won jobs off that board did not strand a column: an adversarial review read the four pools
# and concluded three of the seven were structurally unreachable.
ACTIVE_COLS = ["Created but not sent", "Sent", "Viewed", "Approved", "Deposit submitted",
               "Deposit received", "Contact info"]

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _code() -> str:
    """portal.js with // comment lines stripped — this file's prose quotes what it asserts."""
    return "\n".join(l for l in PORTAL_JS.read_text(encoding="utf-8").splitlines()
                     if not l.strip().startswith("//"))


# A `_block(fn)` helper that lifted one function's source out of portal.js used to live here, and both
# of its callers have been replaced by renders. It is gone with them rather than left available: it
# read markup out of a template literal through a comment-stripper that only understands `//` lines,
# which made every assertion over it weaker than it looked, and having it in the file is an invitation
# to answer the next behavioural question with a substring search.


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(
        ["node", str(HARNESS), str(CORE), str(PORTAL_JS), str(PORTAL_HTML_PATH)],
        capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def drawn():
    """The CRM drawer, RENDERED, out of the harness test_drawer_renders.py drives.

    This file needs two of its scenarios: the not-sent drawer before anybody marked the bid, and the
    same drawer after the real Mark won button was pressed and the panel repainted from the patched
    row. That second one is the state Hanz's instruction is about, and it cannot be reached by
    calling a pure function — the drawer has to save, patch and redraw to get there."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(DRAWER_HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert proc.returncode == 0, (
        "the drawer harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _button(html: str, bid: str):
    """The rendered opening <button> tag carrying one id, or None.

    The whole tag, not a boolean, so a caller can see whether the renderer also wrote `disabled` on
    it. A control that is present and dead is the same bug as a missing one, one step further on."""
    m = re.search(r'<button[^>]*\bid="%s"[^>]*>' % re.escape(bid), html)
    return m.group(0) if m else None


# ── the renderer runs at all ─────────────────────────────────────────────────
@needs_node
def test_every_tab_renders_in_both_views_without_throwing(ran):
    """THE 2026-08-12 FAILURE MODE, first because it is the one that takes the page down rather than
    misfiling a card. A new column constant referenced in kanbanHtml but never bound in portal.js is a
    ReferenceError on the first row of a .map(), which paints nothing at all — while the pills above
    the board stay correct, because they are written before board.innerHTML."""
    assert ran["errors"] == {}, "a tab threw instead of rendering: %s" % ran["errors"]


@needs_node
@pytest.mark.parametrize("tab", ["active", "won", "lost", "test"])
def test_every_row_in_the_pool_becomes_a_card(ran, tab):
    """A card silently dropped is the same bug as a card in the wrong column, one step further on."""
    b = ran["boards"][tab]
    assert b["cards"] == len(ran["pools"][tab]), (
        "the %s board drew %s cards for %s rows" % (tab, b["cards"], len(ran["pools"][tab])))
    assert not b["rawToken"], "an unclosed template literal reached the %s board" % tab
    assert not b["undefinedLeak"], "the %s board printed the word undefined at a reader" % tab


# ── the pools ────────────────────────────────────────────────────────────────
@needs_node
def test_the_four_pools_partition_every_proposal(ran):
    """The property the pills depend on: each row in exactly one pool, and every row in one.

    Mutations this kills: filtering won rows off Active without a Won tab to catch them (the card
    vanishes from the app), and adding the Won pool without taking those rows out of Active (the card
    is in two places and the counts overstate)."""
    seen = [pid for tab in ("active", "won", "lost", "test") for pid in ran["pools"][tab]]
    assert sorted(seen) == sorted(ran["everyId"]), (
        "the tabs do not cover every proposal, so a row is reachable from no tab")
    assert len(seen) == len(set(seen)), "a proposal appears under two tabs, so the counts overstate"


@needs_node
def test_the_project_he_marked_won_is_on_the_won_tab_and_off_the_active_board(ran):
    """THE REPORTED BUG, in one assertion. `{not_sent: true, won_at: "…"}` — Trabon Group."""
    assert "won-unsent" in ran["pools"]["won"], "a project marked won is not on the Won tab"
    assert "won-unsent" not in ran["pools"]["active"], (
        "a project marked won is still on the Active board")
    assert "won-unsent" not in ran["boards"]["active"]["by"]["Created but not sent"], (
        "the card he marked won is still in the Created but not sent bucket, which is the whole bug")


@needs_node
def test_an_unmarked_unsent_bid_is_still_in_created_but_not_sent(ran):
    """The control case. Mutation this kills: routing every not-sent row to the Won tab, which would
    empty the first column of the live board and read as data loss."""
    assert ran["boards"]["active"]["by"]["Created but not sent"] == ["unsent-plain"]


@needs_node
def test_a_won_test_project_stays_under_test(ran):
    """Scratch work does not become real work by being marked won, and Test is the one tab its owner
    looks under. Mutation this kills: testing isWon before is_test in boardPool."""
    assert "won-test" in ran["pools"]["test"]
    assert "won-test" not in ran["pools"]["won"], (
        "somebody's test project is being counted as a job we won")


@needs_node
@pytest.mark.parametrize("pid", ["lost-after-won", "lost-after-marked-won"])
def test_a_job_won_and_then_closed_lost_appears_only_under_lost(ran, pid):
    """Both routes to won, cancelled afterwards. isLost keeps precedence — crm-core's isWon records
    that intent explicitly, because a sent project's closed_lost lives in the portal where the by-hand
    mark cannot see or clear it."""
    assert pid in ran["pools"]["lost"]
    for tab in ("active", "won", "test"):
        assert pid not in ran["pools"][tab], "a cancelled job is on the %s tab as well as Lost" % tab


@needs_node
def test_an_approved_job_with_the_money_still_out_stays_on_the_active_board(ran):
    """THE distinction isWon's derived half exists for, and it matters more now than it did when the
    consequence was a chip: this is the most worth-chasing row there is, and calling it won would take
    it off the board of the person whose job is the chasing."""
    assert "approved-unpaid" in ran["pools"]["active"]
    assert "approved-unpaid" not in ran["pools"]["won"]


# ── the columns: what is still outstanding ───────────────────────────────────
@needs_node
def test_the_won_columns_are_the_outstanding_work_not_the_pipeline(ran):
    """Built from crm-core's WON_COLS rather than typed out again, and asserted in order: the board
    reads left to right as "how much is left", so a reordering is a regression."""
    assert ran["boards"]["won"]["cols"] == ran["wonCols"]
    assert ran["wonCols"] == [WON_EARLY, WON_DEPOSIT, WON_CONTACTS, WON_DONE]


@needs_node
def test_a_win_the_portal_has_not_caught_up_with_lands_in_the_first_column(ran):
    """NOT "Deposit outstanding", and this is the bug the first column was widened for.

    THREE shapes, and each one would be filed as an unpaid invoice by a rule that reads the money
    before the approval:

      won-unsent            never sent. The synthesised row carries no deposit or contacts fields at
                            all, so reading them first invents an invoice for a project the customer
                            has never seen. The card Hanz marked.
      won-marked-sent       sent, unapproved, never invoiced — the verbal yes on the phone, which is
                            what drafts.set_won was built for and the commonest way we learn we won.
      won-marked-nodeposit  the same, on a job that collects no deposit at all. depositSatisfied is
                            TRUE of this one, so a money-only rule sends it to "Contacts outstanding"
                            and asks for contacts the portal will not collect until they approve.

    Nothing downstream of approval is outstanding on any of them, which is what the column says."""
    assert sorted(ran["boards"]["won"]["by"][WON_EARLY]) == sorted(
        ["won-unsent", "won-marked-sent", "won-marked-nodeposit"])


@needs_node
@pytest.mark.parametrize("pid", ["won-marked-sent", "won-marked-nodeposit"])
def test_a_hand_marked_win_is_never_filed_as_money_owed(ran, pid):
    """The regression, stated as the thing that must not happen rather than as where the card goes.

    "Deposit outstanding" is read by the person whose job is chasing money. A proposal nobody has
    invoiced, on a price the customer has not agreed to, must not appear there — and neither must it
    read as waiting on contacts, which are not asked for until approval either."""
    won = ran["boards"]["won"]["by"]
    assert pid not in won[WON_DEPOSIT], (
        "%s says a deposit is outstanding on a proposal nobody has invoiced" % pid)
    assert pid not in won[WON_CONTACTS], (
        "%s says the contacts are outstanding on a proposal the customer has not approved" % pid)


@needs_node
def test_every_won_shape_routes_the_way_the_column_names_claim(ran):
    """The routing table, GENERATED by running the real wonColumn over every distinguishable state a
    won job can be in — so the table anybody reasons from is executed rather than argued.

    The two `deposit_required: false` rows are the pair that pins the rule down. Unapproved, that
    shape belongs in the first column (nothing has been asked of the customer yet); approved, it
    belongs under Contacts outstanding (there is genuinely no money to collect, so the contacts are
    the last thing left). A rule that gates on the money alone cannot tell them apart.

    "approved + deposit requested" carries isWon False on purpose: approval alone is not a win, which
    is why that shape stays on the live board. Its column here is what it WOULD get once somebody
    marks it won, which is the fixture `won-deposit-out`."""
    assert ran["wonRouting"] == {
        "not_sent + won_at": WON_EARLY,
        "sent + won_at": WON_EARLY,
        "sent + won_at + deposit_required false": WON_EARLY,
        "viewed + won_at": WON_EARLY,
        "approved + deposit requested": WON_DEPOSIT,
        "approved + deposit_required false": WON_CONTACTS,
        "deposit received + contacts missing": WON_CONTACTS,
        "everything settled": WON_DONE,
    }
    assert ran["wonRoutingIsWon"]["approved + deposit requested"] is False, (
        "an approved job with the money still out is being called won, which would take the most "
        "worth-chasing row there is off the live board")


@needs_node
def test_a_won_job_with_the_deposit_out_says_so_and_is_off_the_live_board(ran):
    """THE MITIGATION, asserted. This is the card the old keep-it-on-the-board reasoning was
    protecting: moving it is only safe because this column exists to show it."""
    assert ran["boards"]["won"]["by"][WON_DEPOSIT] == ["won-deposit-out"]
    assert "won-deposit-out" not in ran["pools"]["active"]


@needs_node
def test_the_contacts_are_the_last_thing_outstanding(ran):
    """Two ways in, and both belong here: a deposit that arrived, and a job that legitimately collects
    none (deposit_required false and never invoiced). depositSatisfied answers both, which is why
    wonColumn reuses it instead of reading deposit_status on its own.

    BOTH ARE APPROVED, which is what makes the contacts the honest thing to be waiting on — the
    portal does not ask a customer for them until then. `won-marked-nodeposit` is the same money
    shape without the approval and it is deliberately NOT here; before the approval gate it was."""
    assert set(ran["boards"]["won"]["by"][WON_CONTACTS]) == {"won-contacts-out", "won-nodeposit"}


@needs_node
def test_a_job_with_nothing_outstanding_reads_as_complete(ran):
    assert ran["boards"]["won"]["by"][WON_DONE] == ["won-complete"]


# ── what the move did NOT do: strand a column on the live board ──────────────
# An adversarial review printed the Active board's columns after the change, saw "Deposit received"
# and "Contact info" empty, and concluded they were now structurally unreachable: both states imply
# depositSatisfied, which together with approval means isWon, which means the Won tab.
#
# The missing premise is APPROVAL, and the portal takes it back. db.reset_for_revision drops
# proposal_status to 'sent' and NULLS approved_at when a new revision is published, and deliberately
# leaves the deposit and contacts columns alone — "Money that has already been invoiced or paid is a
# fact about the project, not about which revision is current." So a job whose deposit is in, and
# whose contacts are in, can be waiting on an approval again, and it is live work rather than a win:
# money already collected against a price nobody has agreed to yet is the most valuable card on that
# board, and it is exactly the one the review would have deleted the column for.
#
# The three empty columns were a gap in this file's fixtures, not in the product. They are fixtured
# now, so "which columns can a card reach" is answered by a render.
@needs_node
def test_the_active_board_still_draws_the_seven_columns_it_always_had(ran):
    assert ran["boards"]["active"]["cols"] == ACTIVE_COLS


@needs_node
@pytest.mark.parametrize("col", ACTIVE_COLS)
def test_no_active_column_was_stranded_by_moving_won_jobs_off_the_board(ran, col):
    """Every one of the seven has a card in it, RENDERED, on a fixture set where every won job has
    already left. A column no card can reach is a column that should be removed — so this is the
    evidence for that decision, and it says the answer is none of them."""
    assert ran["boards"]["active"]["by"][col], (
        "no card can reach the %s column any more, so the live board carries a heading that can "
        "only ever be empty" % col)


@needs_node
@pytest.mark.parametrize("pid,col", [("revised-deposit-in", "Deposit received"),
                                     ("revised-contacts-in", "Contact info")])
def test_a_revision_puts_a_paid_job_back_on_the_live_board(ran, pid, col):
    """THE shape the review's reasoning could not produce, and the reason those two columns stay.

    The deposit is in and the contacts may be too, and yet the customer has approved nothing: a new
    revision retired the approval it had. Not won, so not on the Won tab; still live, so still being
    chased for the one thing missing."""
    assert ran["boards"]["active"]["by"][col] == [pid]
    assert pid in ran["pools"]["active"]
    assert pid not in ran["pools"]["won"], (
        "a job whose approval a revision retired is being counted as won on the strength of a "
        "deposit that was paid against the old price")


@needs_node
def test_no_card_is_counted_twice_across_the_won_columns(ran):
    flat = [pid for col in ran["boards"]["won"]["by"].values() for pid in col]
    assert sorted(flat) == sorted(ran["pools"]["won"])
    assert len(flat) == len(set(flat))


@needs_node
def test_the_won_tab_cannot_start_a_new_proposal(ran):
    """+ New files a brand-new bid into the column it sits on. "Won before approval" is the near miss:
    a bid started from there would be neither won nor approved. Executed rather than grepped — the gate is
    an expression whose presence in the source says nothing about which tabs it lets through."""
    assert ran["boards"]["won"]["newButton"] is False, (
        "the + New button renders on the Won tab, which would file a new bid as already won")
    assert ran["boards"]["lost"]["newButton"] is False
    for tab in ("active", "test"):
        assert ran["boards"][tab]["newButton"] is True, (
            "the %s tab lost its + New button" % tab)


@needs_node
def test_an_empty_won_tab_says_which_kind_of_empty_it_is(ran):
    """Four empty columns is a page that looks broken. And the two kinds of empty need different
    answers: "nothing won yet" is news, "nothing matches those filters" means clear the filter.

    BOTH BRANCHES RENDERED. This test used to check the unfiltered branch and then assert that the
    string "boardPool().length" appeared in kanbanHtml's source, which says nothing whatever about
    whether the branch it guards is ever taken — and the harness's render() could not take it, because
    it drew exactly the pool it had just computed. The filtered case needs the pool and the drawn list
    to DISAGREE, which is what visible() does on the real page, so the harness now renders that too."""
    unfiltered = ran["emptyWon"]
    assert "Nothing won" in unfiltered
    assert "yet" in unfiltered, "an untouched Won tab reads as a filter problem"
    assert "filter" not in unfiltered, (
        "an unfiltered empty tab is telling the reader to clear a filter they have not set")
    assert 'class="col' not in unfiltered, (
        "an empty Won tab still draws its four columns, which reads as a broken page")

    filtered = ran["emptyWonFiltered"]
    assert filtered["pool"] and not filtered["shown"], (
        "the filtered scenario is not filtered: %s in the pool, %s drawn"
        % (filtered["pool"], filtered["shown"]))
    assert "Nothing won matches those filters." in filtered["html"], (
        "a Won tab emptied by the toolbar says nothing has been won, so the reader clears nothing "
        "and concludes the board is broken: %s" % filtered["html"])
    assert 'class="col' not in filtered["html"]


# ── the card still carries its facts ─────────────────────────────────────────
@needs_node
def test_a_won_unsent_card_still_shows_its_money_and_its_estimator(ran):
    """A card that moved tab must not lose what makes it worth reading. The money comes from
    `bid_total` on a synthesised row (cardTotal reads both fields, and calling an unsent draft's
    working figure "approved" would put a word on it nobody has earned), and the estimator falls back
    to whoever priced it, drawn with a "?" because nobody chose them."""
    card = re.search(r'<div class="deal" data-id="won-unsent">.*?\n        </div>',
                     ran["boards"]["won"]["html"], re.S)
    assert card, "the card he marked won did not render on the tab it moved to"
    body = card.group(0)
    assert "$88,000.00" in body, "the bid value is gone from the card: %s" % body
    assert "Kyle" in body, "the estimator is gone from the card"
    assert "chip-won" in body, "nothing on the card says why it is on this board"


@needs_node
def test_the_won_tab_reads_as_pressed_and_the_four_counts_add_up(ran):
    """syncTabs computes its numbers inline rather than through boardPool (which closes over TAB), so
    the precedence is spelled out twice and this is what catches the two copies drifting. A pill
    advertising 3 and then showing 2 is worse than no number at all."""
    counts = ran["counts"]
    assert set(counts) == set(ran["pills"]), (
        "syncTabs and the markup disagree about which pills exist: %s vs %s"
        % (sorted(counts), sorted(ran["pills"])))
    assert sum(counts.values()) == len(ran["everyId"]), (
        "the four pill counts sum to %s, not the %s proposals there are"
        % (sum(counts.values()), len(ran["everyId"])))
    for tab in ran["pills"]:
        assert counts[tab] == len(ran["pools"][tab]), (
            "the %s pill says %s and the board shows %s" % (tab, counts[tab], len(ran["pools"][tab])))
    assert ran["pressed"]["won"] == "true", "the Won pill does not read as selected on the Won tab"


# ── mark won OR lost, on a bid nobody has sent ───────────────────────────────
# Hanz, 2026-08-20: "Even for created not sent we must be able to mark it as won or lost."
#
# BOTH CONTROLS ALREADY WORKED: portal.js renderNotSent renders the Won control and the Mark closed
# lost button into the Follow-up panel of every not-sent drawer, wireWon and wireNotSentLost bind
# them, and both post to /api/draft/<id>/status. test_drawer_renders.py executes that panel
# (test_both_drawers_offer_the_mark on the "notSentOffered" scenario, and the CONDITIONAL_IDS pass
# over ns-lost / ns-reopen / won-mark / won-undo).
#
# What is NEW is that the card MOVES, so the PAIR has to survive the move: the drawer is reached from
# whichever tab the card is on, and a won unsent bid the GC then cancels must be closeable without
# being un-won first. The wonControlHtml tests below cover the won half on its own, on both of the
# shapes the first column holds; test_both_outcome_controls_survive_marking_an_unsent_bid_won covers
# the pair, in the rendered drawer, on both sides of a real button press.
@needs_node
@pytest.mark.parametrize("pid", ["won-unsent", "won-marked-sent"])
def test_the_drawer_offers_the_undo_on_a_bid_somebody_marked_won(ran, pid):
    """RENDERED, from the real wonControlHtml. `if (false) …won-undo…` leaves the id in the function
    and keeps a source check green while offering nothing.

    Both shapes the first Won column now holds: never sent, and sent-but-unapproved. The undo has to
    be there for the second one as much as the first — that is the mark most likely to be wrong,
    because it is the one somebody made off a phone call."""
    html = ran["wonControl"][pid]
    assert 'id="won-undo"' in html, "a bid marked won offers no way back"
    assert 'id="won-mark"' not in html, "it offers to mark a project it has already marked"
    assert "Won tab" in html, (
        "the panel does not say where the card went, which is exactly what he could not find")


@needs_node
def test_the_drawer_offers_the_mark_on_an_unsent_bid_nobody_has_marked(ran):
    html = ran["wonControl"]["unsent-plain"]
    assert 'id="won-mark"' in html, "an unsent bid cannot be marked won from its drawer"
    assert 'id="won-undo"' not in html


@needs_node
def test_a_job_won_by_the_numbers_has_no_button_and_the_copy_says_why(ran):
    """THE ONE STATE WITH NOTHING TO BRING BACK. Hanz asked for the bring-back on 2026-08-20 and
    this is the case it cannot serve: approved, deposit in, contacts in, and NOBODY marked it won —
    the numbers did. There is no mark to clear, so an Undo here would save and change nothing, which
    reads as a broken control.

    The decision was to keep having no button and to SAY SO, because a gap where every other state
    has a control is indistinguishable from a control that failed to render. The two things that
    would actually un-win this job are un-approving it and unwinding the deposit, and the copy points
    at where those live rather than pretending this panel can do them."""
    html = ran["wonControl"]["won-complete"]
    assert html, "the derived-won panel renders nothing at all"
    assert 'id="won-undo"' not in html, (
        "it offers to take off a mark nobody made, which would change nothing visible")
    assert 'id="won-mark"' not in html, "it offers to mark a job that already counts as won"
    assert "nothing to bring back" in html, (
        "the panel is silent about why it has no control: %r" % html)
    assert "Proposal tab" in html, (
        "it does not say where un-approving it or unwinding the deposit actually live")


@needs_node
def test_a_closed_lost_bid_is_offered_neither(ran):
    """Lost beats Won everywhere, so a Mark won press here would save and change nothing visible,
    which reads as a broken control. Reactivate beside it is the way back."""
    assert ran["wonControl"]["lost-after-won"] == ""


@needs_node
def test_both_outcome_controls_survive_marking_an_unsent_bid_won(drawn):
    """Hanz, 2026-08-20: "Even for created not sent we must be able to mark it as won or lost."

    RENDERED, on both sides of the mark. This test used to read renderNotSent's source and assert
    that the string "isWon" did not appear in a slice of it — and the slice came from a helper that
    strips only `//` lines, over markup inside a template literal, so it was far weaker than it read
    and could not see a gate written any other way. What matters is not which identifier appears in
    the function; it is that a rep looking at a bid nobody has sent is offered both outcomes, before
    and after somebody records one of them.

    The "after" state is the drawer the real Mark won button repainted from the row it patched, which
    is the state the card MOVING tab makes load-bearing: a won unsent bid the GC then cancels has to
    be closeable without being un-won first."""
    assert not drawn["errors"], "the drawer threw instead of rendering: %s" % drawn["errors"]
    before = drawn["won"]["notSentOffered"]["html"]
    after = drawn["won"]["notSentMarked"]
    assert after["rowWonAt"], (
        "the mark never saved, so the 'after' panel is not the won state and this test proves "
        "nothing about it")

    for label, html, won_id in (("before the mark", before, "won-mark"),
                                ("after the mark", after["html"], "won-undo")):
        lost = _button(html, "ns-lost")
        won = _button(html, won_id)
        assert lost, "%s: the not-sent drawer offers no Mark closed lost" % label
        assert won, "%s: the not-sent drawer offers no %s control" % (label, won_id)
        assert "disabled" not in lost, "%s: Mark closed lost renders dead: %s" % (label, lost)
        assert "disabled" not in won, "%s: the won control renders dead: %s" % (label, won)
    # And the two are genuinely different states, or the loop above passed twice on one panel.
    assert _button(before, "won-undo") is None
    assert _button(after["html"], "won-mark") is None


# ── the things a source read is the right tool for ───────────────────────────
def test_the_tab_is_one_named_set_and_the_markup_has_a_pill_for_each():
    """TAB is validated against TABS on load, so a tab missing from that list cannot be restored from
    a stored session, and a pill missing from the markup cannot be clicked."""
    code = _code()
    m = re.search(r"const TABS = \[([^\]]*)\]", code)
    assert m, "the tab list is not one named set, so the stored value and the markup can drift"
    tabs = re.findall(r'"([a-z]+)"', m.group(1))
    assert "won" in tabs, "Won is not in TABS, so a stored Won tab falls back to Active"
    for t in tabs:
        assert 'data-tab="%s"' % t in PORTAL_HTML, "the %s tab has no pill in the markup" % t


def test_the_won_column_rule_lives_in_crm_core_beside_stage():
    """One definition, in the module with no DOM that node exercises. Two copies of "is the deposit
    in" is how a card ends up under "Deposit outstanding" here while the pipeline calls it "Deposit
    received"."""
    core = CORE.read_text(encoding="utf-8")
    assert "function wonColumn" in core and "wonColumn: wonColumn" in core, (
        "wonColumn is not defined and exported by crm-core")
    assert "depositSatisfied(p)" in core.split("function wonColumn")[1][:600], (
        "wonColumn is not reusing depositSatisfied, so the Won tab has its own idea of an unpaid "
        "deposit")
    body = core.split("function wonColumn")[1][:600]
    assert "approvedInPortal(p)" in body, (
        "wonColumn is not reusing approvedInPortal, so the Won tab has its own idea of an approved "
        "proposal — which is how a hand-marked win ends up filed as an unpaid invoice")
    assert "approvedInPortal(p)" in core.split("function isWon")[1][:400], (
        "isWon has stopped sharing that definition, so the tab and the pool can disagree about "
        "which cards the first column is even reachable by")
    js = PORTAL_JS.read_text(encoding="utf-8")
    assert "function wonColumn" not in js and "function groupWon" not in js, (
        "portal.js has grown its own copy of the Won grouping")


# There is deliberately NO test here pinning the chipsHtml note that records the 2026-08-19 reversal.
# One existed and asserted that "2026-08-20" and the word "REVERSE" appeared in that comment, which
# could only ever fail if somebody edited prose: it caught no code change at all and reported coverage
# of a decision nobody had tested. The comment is worth keeping and is still there; pretending it was
# covered is what had to go.
