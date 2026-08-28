"""The Lost tab: where a closed-lost project lives, and why its columns are reasons.

Hanz, 2026-08-12, looking at the Active / Test pills on production:

    "In thes tabs Actualy create another tab for "Lost" This is where the lost projects will be
     held"

WHAT THIS REPLACED, AND WHY THE REPLACEMENT IS NOT A REVERSAL. On 2026-08-10 he had closed-lost
proposals taken OFF this board: "if its lost remove it from the Customer CRM. To remove clutter."
Asked where they should still be reachable, he chose a count. That count became a link to
/projects.html — and the link could not do what it implied. That page reads no filter from the URL,
its tabs are Active / Inactive / All / Test, and it lists our own drafts rather than portal rows, so
it has never heard of `closed_lost`. You landed on an unfiltered list to hunt through. A tab honours
both asks at once: dead deals still take up no room on a board of live work, and there is now
somewhere that actually shows them.

WHY THE COLUMNS ARE THE CLOSE REASONS. Every card on this tab has the same stage, so grouping by
stage would give one tall column and answer nothing. The close dialog already refuses free text and
offers a fixed six precisely so "why do we lose bids?" has an answer — this is where that answer is
readable. A reason the board does not recognise lands in "Not recorded" rather than vanishing, the
same bias C.group takes with an unknown stage.

WHY A LOST TEST PROJECT SHOWS UP HERE. Lost is every dead deal. The Test tab has always excluded
lost rows, so filtering them out of Lost as well would leave them reachable from nowhere and make
the tab's own count a lie. They carry a Test chip instead, which is the only place on the board
where that chip appears — on the live tabs the tab itself is the label.

THE POOLS PARTITION THE ROWS, and that property is worth more than any single assertion here: it is
what makes the tab badges add up, and what guarantees no proposal can fall between them. There were
three pools until 2026-08-20, when a fourth tab joined Lost in taking cards off the live board. That
fourth tab was Won until 2026-08-28 and is Handed Off since: a won job still owes a deposit and a
set of contacts, so it belongs in front of the sales meeting, and what takes a card off the board is
now a person pressing Hand it off (see test_handed_off_tab.py, and the note above the last test in
this file). The partition is over four either way, and it is asserted over whatever `TABS` actually
holds rather than over a list typed here, so a fifth tab cannot arrive without this claim being
checked against it.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "lost-tab-harness.js"
CORE = FRONTEND / "js" / "crm-core.js"
PORTAL_JS = FRONTEND / "js" / "portal.js"
PORTAL_HTML = (FRONTEND / "portal.html").read_text(encoding="utf-8")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _code() -> str:
    """portal.js with // comment lines stripped — this file's prose quotes what it asserts."""
    return "\n".join(l for l in PORTAL_JS.read_text(encoding="utf-8").splitlines()
                     if not l.strip().startswith("//"))


def _block(fn: str) -> str:
    src = _code()
    m = re.search(r"\n\s{2,6}function " + re.escape(fn) + r"\s*\(", src)
    assert m, "%s() is gone from portal.js: rewrite these tests, don't delete them" % fn
    i = src.index("{", m.end() - 1)
    depth = 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    pytest.fail("unbalanced braces reading %s()" % fn)


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(CORE), str(PORTAL_JS)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── what each tab holds, run for real ────────────────────────────────────────
@needs_node
def test_the_lost_tab_holds_the_lost_projects(ran):
    """The whole ask, in one assertion."""
    # lost-after-won is a job that was approved and paid and then cancelled. It belongs here:
    # closed-lost is checked before anything else, on this board and on the notification page.
    assert set(ran["pools"]["lost"]) == {"lost-price", "lost-test", "lost-noreason",
                                         "lost-unknown", "lost-after-won",
                                         "lost-after-marked-won"}


@needs_node
def test_a_lost_project_is_off_every_other_tab(ran):
    """His 2026-08-10 constraint, still enforced: a dead deal must not clutter live work.

    Over every tab but Lost, derived from TABS — this said "both live tabs" and checked active and
    test by name, which stopped being every other tab when a fourth arrived on 2026-08-20. Two of the
    fixtures are jobs that were won (one derived, one marked by hand) and then cancelled, and since
    2026-08-28 a won job STAYS on the Active board, so those two are exactly the rows that a pool
    asking about the win before the cancellation would leave sitting among live work. Lost is asked
    first, everywhere, for that reason."""
    for tab in ran["tabs"]:
        if tab == "lost":
            continue
        assert not [i for i in ran["pools"][tab] if i.startswith("lost-")], (
            "a closed-lost proposal is back on the %s tab" % tab)


@needs_node
def test_a_lost_TEST_project_is_under_lost_and_not_under_test(ran):
    """Test has always excluded lost rows. Excluding them from Lost as well would make the row
    reachable from nowhere at all and the tab's count wrong."""
    assert "lost-test" in ran["pools"]["lost"]
    assert "lost-test" not in ran["pools"]["test"]


@needs_node
def test_every_tab_together_partitions_every_proposal(ran):
    """The property the badges depend on: each row in exactly one pool, and every row in one.

    SUMMED OVER `TABS` ITSELF, not over a list of tab names typed here. It was active + test + lost
    until 2026-08-20, when a fourth tab arrived and this stopped covering the rows — the sum was
    short by three, and a hand-written sum can only ever be short by however many tabs the board has
    grown since somebody last edited this line. The harness derives the pools from portal.js's own
    TABS, so a fifth tab is partitioned or this fails.

    Mutations this kills: making Lost `isLost(p) && !isTest(p)`, which silently strips the lost test
    projects out of the only tab that would have shown them; filtering handed-off rows off Active
    with no Handed Off pool to catch them, which leaves the card reachable from no tab at all and
    looks to the estimator like data loss; and adding the Handed Off pool without removing those rows
    from Active, which double-counts them and makes both badges wrong.

    All three were run against a mutated copy of portal.js on 2026-08-28, and each one fails here.
    WHAT A PARTITION CANNOT SEE is a swap that keeps every row in exactly one pool — routing the
    won rows to Handed Off and the handed-off one to Active satisfies this test completely. That
    belongs to the tests that name the row: test_a_lost_TEST_project_is_under_lost_and_not_under_test
    here, test_a_won_job_stays_on_the_board_and_only_a_hand_off_takes_it_off at the foot of this
    file, and test_a_test_project_stays_under_test_however_it_was_marked in test_handed_off_tab.py."""
    pools = ran["pools"]
    assert sorted(pools) == sorted(ran["tabs"]), (
        "the harness did not visit every tab portal.js names, so this partition is over a subset")
    seen = [pid for tab in ran["tabs"] for pid in pools[tab]]
    assert sorted(seen) == sorted(ran["everyId"]), (
        "the tabs do not cover every proposal, so a row is reachable from no tab")
    assert len(seen) == len(set(seen)), "a proposal appears under two tabs, so the counts overstate"


# ── the columns ──────────────────────────────────────────────────────────────
@needs_node
def test_the_columns_are_exactly_the_reasons_the_close_dialog_can_produce(ran):
    """Built from C.LOST_REASON rather than typed out again: a seventh reason added to the dialog
    has to grow a column, or every proposal closed for it lands in "Not recorded"."""
    assert ran["cols"] == ran["reasonLabels"] + ["Not recorded"], (
        "the Lost columns and the close dialog's reasons have drifted apart")


@needs_node
def test_each_lost_project_lands_under_its_own_reason(ran):
    assert ran["grouped"]["Price"] == ["lost-price"]
    assert ran["grouped"]["Timing"] == ["lost-test"]


@needs_node
def test_a_project_closed_before_we_asked_why_still_appears(ran):
    """The reason field arrived after the status did, so old rows have none. Dropping them would
    lose real history from the only page that shows it."""
    assert "lost-noreason" in ran["grouped"]["Not recorded"]


@needs_node
def test_an_unrecognised_stored_reason_does_not_drop_the_card(ran):
    """`(by[lostReason(p)] || by["Not recorded"]).push(p)`. Mutation this kills: pushing straight
    into `by[lostReason(p)]`, which throws on the first unknown value and blanks the whole board —
    C.group takes the same bias with an unknown stage, for the same reason."""
    assert "lost-unknown" in ran["grouped"]["Not recorded"], (
        "a reason the board does not recognise loses the card")


@needs_node
def test_no_card_is_counted_twice_across_the_columns(ran):
    flat = [i for col in ran["grouped"].values() for i in col]
    assert sorted(flat) == sorted(ran["pools"]["lost"])
    assert len(flat) == len(set(flat))


# ── the things a source read is the right tool for ───────────────────────────
def test_the_lost_tab_cannot_start_a_new_proposal():
    """+ New files a brand-new bid into the column it sits on. On a board of dead deals that is
    the worst button in the app, so the gate carries the tab as well as the column name."""
    kanban = _block("kanbanHtml")
    m = re.search(r"const add = (.+?)\n", kanban, re.S)
    assert m, "the + New gate is no longer one expression"
    assert "!lost" in m.group(1), (
        "the + New button is not gated off the Lost tab; only the column name stands between a "
        "new bid and being filed as closed lost")


@needs_node
def test_a_test_project_says_so_on_the_lost_tab(ran):
    """It is the one board where test and real work sit together, so the card has to carry it.

    RENDERED, not grepped. `if (false) out.push(...chip-test...)` leaves the class name sitting in
    the function, keeps a presence check green, and labels nothing — that mutation survived the
    first version of this test."""
    assert "Test" in ran["chips"]["lost-test"], (
        "a lost test project is indistinguishable from a real dead deal")
    assert "Test" not in ran["chips"]["lost-price"], "a real dead deal is labelled as a test"


@needs_node
def test_the_test_chip_appears_ONLY_on_a_lost_card(ran):
    """On the live tabs the tab IS the label, so a Test chip on every card of the Test tab would
    say nothing and add noise to every row."""
    for pid in ("live-test", "live-active"):
        assert "chip-test" not in ran["chips"][pid], (
            "%s carries a Test chip outside the Lost tab" % pid)


def test_the_test_chip_is_styled():
    assert ".chip-test" in PORTAL_HTML, "the Test chip has no styling, so it renders as a bare pill"


# ── the Won chip: the card saying out loud that the customer said yes ─────────
# Hanz, 2026-08-19: "CRM lost and won should also tie up to the notification sending okay?"
#
# The two screens share one isWon, in crm-core. One definition, so a board and a page cannot come to
# disagree about a word Troy reads as a number.
#
# THIS BLOCK HAS SAID BOTH THINGS, and the 2026-08-19 answer is the one that stood. The original
# reasoning was that this board KEEPS a won card, because a won job still has work on it — the deposit
# and the contacts, both live columns — and moving the card hides that work from the people doing
# it. So the chip was how the board said the word out loud without moving anything. Hanz reversed it
# on 2026-08-20 ("I marked Trabon Group project as Won but it's still in the Created but Not Sent
# bucket"), and won jobs left for a tab of their own for eight days.
#
# ON 2026-08-28 HE PUT THEM BACK, because the complaint was never that the card was ON the board:
# it was that the card was in the wrong COLUMN, and taking it off the board answered him by hiding
# the thing he was pointing at. The real fix is stage() reading the won mark above not_sent, so the
# card sits in Won/Approved and the column and the chip finally say the same thing. What takes a
# card off this board now is a person pressing Hand it off — test_handed_off_tab.py owns that tab;
# what this file owns is Lost, the chip, and which tab holds a card.
#
# The chip survives both reversals because a card FURTHER ALONG than Won/Approved — Deposit received,
# Contact info — is also won, and its column no longer says so; the chip is then the only thing on
# the card that does. A won TEST project stays under Test, where it is the only marker at all.
@needs_node
@pytest.mark.parametrize("pid", ["won-paid", "won-nodeposit"])
def test_a_won_job_says_so_on_its_card(ran, pid):
    """Both routes to won: approved with the deposit received, and approved on a job that
    legitimately collects none. RENDERED, because `if (false) out.push(...chip-won...)` leaves the
    class in the function and keeps a source check green while labelling nothing."""
    assert "chip-won" in ran["chips"][pid], "%s does not say it was won" % pid
    assert ">Won<" in ran["chips"][pid], (
        "the chip has no word in it, and this page gets a synthesised dark theme in some browsers "
        "that rewrites the tint")


@needs_node
def test_an_approved_job_with_the_money_still_out_is_not_won(ran):
    """THE distinction the predicate exists for. This is the most worth-chasing row on the board,
    and a Won chip on it tells the estimator the job is finished."""
    assert "chip-won" not in ran["chips"]["approved-unpaid"], (
        "an approved job with an outstanding deposit is being called won")


@needs_node
def test_a_job_won_and_then_cancelled_reads_as_lost_only(ran):
    """A card claiming both would be worse than either. Lost is checked first, which is the same
    order crm-core's stage() and the notification page's ppCategory use."""
    chips = ran["chips"]["lost-after-won"]
    assert "chip-lost" in chips
    assert "chip-won" not in chips, "the card says it was both won and lost"


@needs_node
def test_a_job_marked_won_by_hand_says_so_on_the_board_too(ran):
    """Hanz, 2026-08-19: "Is there any way to also mark as won for now other than after the deposit
    has been received". Neither half of the derived rule is true of this row — sent, unapproved, no
    deposit — so without the chip the card reads as untouched work and the colleague who took the call
    has no way to tell anyone."""
    chips = ran["chips"]["won-marked"]
    assert "chip-won" in chips, "a project somebody marked won looks identical to one nobody has"
    assert ">Won<" in chips


@needs_node
def test_a_job_marked_won_and_then_cancelled_reads_as_lost_only(ran):
    """The manual mark does not buy its way past Lost. Nothing in isWon checks isLost, so this is the
    reader's ordering doing the work — and it has to, because a sent project's closed_lost lives in
    the portal where the mark cannot reach it."""
    chips = ran["chips"]["lost-after-marked-won"]
    assert "chip-lost" in chips
    assert "chip-won" not in chips, "the card says it was both marked won and lost"


@needs_node
@pytest.mark.parametrize("pid", ["won-paid", "won-nodeposit", "won-marked"])
def test_a_won_job_stays_on_the_board_and_only_a_hand_off_takes_it_off(ran, pid):
    """THE REVERSAL, REVERSED — and asserted as the contrast, because either half alone is weak.

    This was `test_a_won_job_stays_on_the_board` on 2026-08-19, flipped to
    `test_a_won_job_comes_off_the_active_board_onto_the_won_tab` on 2026-08-20 after "I marked Trabon
    Group project as Won but it's still in the Created but Not Sent bucket", and is back to the first
    claim since 2026-08-28. That is not indecision: his complaint was about the COLUMN, and moving the
    card off the board answered it by hiding the card he was complaining about. Winning no longer
    moves a card at all — stage() files it under Won/Approved — because a won job still owes a deposit
    and a set of contacts, and the sales meeting is run off the Active board. A card the meeting
    cannot see is a card nobody chases.

    All three routes to won are covered, because the hand mark is not another input to the derived
    rule but a person overriding it: approved-and-paid, approved-with-no-deposit-to-collect, and
    marked by hand on a bid neither of those is true of. A rule that kept only the derived ones would
    lose the exact card he reported.

    ASSERTED AGAINST `handoff-done` IN THE SAME BREATH, because "this id is on Active" is equally
    true of a board nothing ever leaves. Both mutations were run against a copy of portal.js on
    2026-08-28 and both survive the partition test above, which cannot see a swap that keeps every
    row in exactly one pool: putting the pool back on isWon moves the three won ids off Active, and
    a pool predicate that never fires strands handoff-done there. The contrast fails on both.

    WHICH COLUMN a won card lands in is test_handed_off_tab.py's claim, not this file's — this one
    owns which TAB holds it."""
    assert pid in ran["pools"]["active"], (
        "%s left the Active board without anybody handing it off, so a job that still owes a deposit "
        "is invisible to the meeting the board is run from" % pid)
    assert pid not in ran["pools"]["handed_off"], (
        "%s is on the Handed Off tab, which claims operations already has it" % pid)
    assert "handoff-done" in ran["pools"]["handed_off"], (
        "a job somebody pressed Hand it off on is not on the Handed Off tab")
    assert "handoff-done" not in ran["pools"]["active"], (
        "a handed-off job is still among the live bids, so nothing ever leaves this board")


def test_the_won_chip_is_styled():
    assert ".chip-won" in PORTAL_HTML, "the Won chip has no styling, so it renders as a bare pill"


def test_won_is_defined_once_for_both_screens():
    """The substance of "tie up". Two copies of this predicate is how the board and the
    Notification Sending page start disagreeing about a word Troy reads as a number."""
    core = (FRONTEND / "js" / "crm-core.js").read_text(encoding="utf-8")
    assert "function isWon" in core and "isWon: isWon" in core, (
        "isWon is not defined and exported by crm-core")
    for page in ("portal.js", "notifications.js"):
        js = (FRONTEND / "js" / page).read_text(encoding="utf-8")
        assert "function isWon" not in js, "%s has its own copy of isWon" % page
        assert "isWon" in js, "%s does not use the shared isWon at all" % page


def test_an_empty_lost_tab_says_which_kind_of_empty_it_is():
    """Seven empty reason columns is a page that looks broken. And "nothing lost" and "nothing
    matches your filter" need different answers — one is good news, the other means clear the
    filter."""
    kanban = _block("kanbanHtml")
    assert "Nothing closed lost" in kanban
    assert "boardPool().length" in kanban, (
        "the empty state cannot tell an unfiltered empty tab from a filtered one")


def test_the_tab_survives_a_reload_like_the_other_two():
    code = _code()
    assert 'ssSet(TAB_KEY, TAB)' in code or re.search(r"ssSet\(TAB_KEY,\s*TAB\b", code), (
        "the chosen tab is not stored verbatim, so Lost cannot be remembered")


def test_switching_to_lost_actually_switches():
    """The click handler used to coerce anything that was not "test" to "active" — Lost would have
    read as pressed and shown the Active board."""
    code = _code()
    i = code.index('tabs.addEventListener("click"')
    handler = code[i:code.index("if (view)", i)]
    assert 'TABS.includes' in handler, (
        "the tab click still coerces to a two-way choice, so Lost falls back to Active")
    assert '=== "test" ? "test" : "active"' not in handler, (
        "the old two-tab coercion is still in the click handler")
