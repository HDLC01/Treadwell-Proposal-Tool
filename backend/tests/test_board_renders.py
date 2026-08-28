"""The Active Projects board RENDERS. Executed, not grepped.

THE INCIDENT THIS EXISTS FOR — 2026-08-12, production. Hanz: "why isnt this loadiang?" The board sat
on "Loading…" for ever. The tab counts above it were correct (Active 11, Test 10, Lost 0) and so was
"11 proposals", which is what made it confusing: the data had arrived and the page still drew nothing.

    ReferenceError: STAGE_CREATED is not defined

`kanbanHtml` gained `s === STAGE_CREATED` to decide which column carries the + New button. crm-core
exports that constant. portal.js destructured `STAGES, STAGE_SUBMITTED, NATURAL_DIR, SORT_FIELDS` off
it and never STAGE_CREATED. An unresolved identifier inside a `.map()` callback throws on the FIRST
row, so nothing painted — and the counts were already written, because `renderBoard` sets them
BEFORE `board.innerHTML`.

WHY EVERY EXISTING TEST PASSED. All of them read the source as text:

    assert "s === STAGE_CREATED" in gate

That string was present. The identifier it names was not bound. Several of those tests were written
specifically to defeat mutations of that very expression, and they were mutation-tested — but a
mutation run only proves a test fails when the source CHANGES; it cannot notice that the unmutated
source was already broken. Nothing in this repo had ever executed the renderer.

WHAT THIS FILE DOES INSTEAD. It runs the real `kanbanHtml`/`tableHtml` out of the real portal.js,
over rows shaped like the ones production serves, on EVERY tab the page declares and in both views —
with ONLY the names portal.js actually binds in scope. Any identifier the page uses without importing
is an immediate ReferenceError, which is the entire point. Deliberately not jsdom: a stubbed global
would let exactly this bug hide again.

"EVERY TAB THE PAGE DECLARES" IS NOT A LIST TYPED HERE. It used to be `("active", "test", "lost")`,
and when the board grew a fourth tab (Won, 2026-08-20) this file went on rendering three of four and
staying green — the same failure as the incident above, one level up: the guard existed and did not
cover the new code. The tab list now comes out of portal.js's own `const TABS`, and the harness reads
it independently and reports what it read, so the two derivations have to agree with each other AND
with the [data-tab] pills in portal.html.

The harness also asserts the reverse direction — that every name portal.js destructures off crm-core
is really exported — so a rename in crm-core fails here rather than in a browser.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "board-render-harness.js"
CORE = FRONTEND / "js" / "crm-core.js"
PORTAL_JS = FRONTEND / "js" / "portal.js"
PORTAL_HTML = FRONTEND / "portal.html"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _declared_tabs():
    """portal.js's own tab list. Read here as well as in the harness because pytest needs the
    parametrize ids at collection time, before any subprocess runs — and because two independent
    reads of one declaration is a cheap check that neither read has rotted (see
    test_the_tab_list_is_the_products_own)."""
    src = PORTAL_JS.read_text(encoding="utf-8")
    m = re.search(r"\n\s*const TABS = (\[[^\]]*\]);", src)
    assert m, "portal.js no longer declares `const TABS = [...]` — rewrite this test, don't delete it"
    return json.loads(m.group(1))


TABS = _declared_tabs()
# The tabs that draw the PIPELINE. boardPool has exactly two exceptions to that — Lost, columned by
# close reason, and Handed Off, which is one flat column — so this is stated as "everything else"
# rather than as a list: a fifth tab then lands in here and fails the column-identity assertions
# below out loud, which is the right way for a new tab to reach whoever maintains this file.
#
# The exclusion list is spelled with the tab IDS, and `handed_off` carries an underscore. A pattern
# that assumes ids are letters-only drops that tab silently, which is the failure this whole file
# exists to make loud.
LIVE_TABS = tuple(t for t in TABS if t not in ("lost", "handed_off"))


@pytest.fixture(scope="module")
def rendered():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(CORE), str(PORTAL_JS), str(PORTAL_HTML)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


COMBOS = [(t, v) for t in TABS for v in ("board", "table")]


# ── the one that would have caught it ────────────────────────────────────────
@needs_node
@pytest.mark.parametrize("tab,view", COMBOS)
def test_it_renders_without_throwing(rendered, tab, view):
    """THE test. Every tab, both views, executed. An unbound identifier anywhere in the render path
    lands here as a ReferenceError naming itself."""
    key = "%s/%s" % (tab, view)
    assert key not in rendered["errors"], (
        "the %s view of the %s tab throws: %s" % (view, tab, rendered["errors"].get(key)))
    assert key in rendered["results"], "the harness never rendered %s" % key


@needs_node
def test_the_tab_list_is_the_products_own(rendered):
    """The guard on the guard. This file renders `TABS`, so if that list is not the page's real one
    a whole tab can be untested while every test here passes — which is exactly what happened to the
    Won tab. Three independent reads of the same fact have to agree: portal.js's `const TABS` (read
    twice, here and in the harness) and the [data-tab] pills portal.html actually ships.

    The pills assertion earns its keep a second way since 2026-08-28: tab ids now contain an
    underscore (`handed_off`), and anything that matches them as `[a-z]+` drops that pill and reports
    it as a missing button. A tab dropped by a character class looks exactly like a tab nobody
    built."""
    assert rendered["tabs"] == TABS, (
        "the harness and this file disagree about portal.js's tab list: %s vs %s"
        % (rendered["tabs"], TABS))
    assert rendered["pills"] == TABS, (
        "portal.html's tab buttons are %s but portal.js declares %s — a tab with no button is "
        "unreachable, and a button with no tab blanks the board"
        % (rendered["pills"], TABS))
    assert "handed_off" in TABS, (
        "the Handed Off tab is gone from portal.js. If that was deliberate, delete the hand-off "
        "assertions below with it; until then this is the tab a job lands on when somebody presses "
        "Hand it off — and pressing it is the only thing that takes a card off the Active board")
    for tab in TABS:
        assert "%s/board" % tab in rendered["results"], (
            "the harness never rendered the %s tab" % tab)


@needs_node
def test_stage_created_is_imported_not_merely_mentioned(rendered):
    """The specific regression, named. It is asserted through the harness's own import list rather
    than by grepping portal.js, because grepping is what missed it: the string was there."""
    assert "STAGE_CREATED" in rendered["imported"], (
        "portal.js uses STAGE_CREATED for the + New column but does not destructure it off "
        "crm-core — this is the exact bug that took the board down on 2026-08-12")


@needs_node
def test_every_name_taken_off_crm_core_really_exists(rendered):
    """The other direction: renaming an export in crm-core must fail here, not in a browser. The
    harness raises while building its scope if portal.js asks for something crm-core lacks, so
    reaching this assertion at all is most of the proof."""
    assert len(rendered["imported"]) >= 10, rendered["imported"]


# ── that it drew the right thing, not merely something ───────────────────────
@needs_node
def test_the_live_tabs_draw_the_pipeline_columns(rendered):
    """The pipeline, by NAME as well as by count.

    The count assertion used to read `== 8` with the message "the pipeline has 8". The number is
    right and the reason was wrong: C.STAGES has SEVEN stages, and the eighth match is the + New
    button, whose `class="col-add"` also contains the string the harness counts. Kept — a live tab
    really must render seven columns and that button — with the arithmetic said out loud, and backed
    by the heading names, which is the assertion that can tell one column set from another."""
    stages = rendered["stages"]
    assert len(stages) == 7, stages
    for tab in LIVE_TABS:
        r = rendered["results"]["%s/board" % tab]
        assert r["colNames"] == stages, (
            "the %s board drew %s; the pipeline is %s" % (tab, r["colNames"], stages))
        assert r["columns"] == len(stages) + 1, (
            "the %s board matched `class=\"col` %s times; expected %s columns plus the col-add "
            "button" % (tab, r["columns"], len(stages)))


@needs_node
def test_the_lost_tab_draws_the_reason_columns(rendered):
    """Every close reason plus "Not recorded", by NAME.

    This read `== 7` until 2026-08-20 — six invented reasons and the catch-all. Kyle's own list
    replaced them that day and the map became a superset: his seven close-lost answers plus the
    four only the CUSTOMER's own form can produce, which stay so a bid the customer closed
    themselves still has a column. That is eleven and the catch-all, twelve. A hardcoded count
    would have to be edited every time the vocabulary moves and says nothing about WHICH columns
    were drawn, so this asserts against crm-core's own derived LOST_REASON (the harness builds
    `lostCols` the way portal.js builds LOST_COLS) and against the pipeline it must not be.

    The two HOLD answers must not appear: a held bid is on the Active board, so a Lost column
    headed "Project on Hold" would be a column of live work on the tab of dead work."""
    r = rendered["results"]["lost/board"]
    lost_cols = rendered["lostCols"]
    assert lost_cols[-1] == "Not recorded", lost_cols
    assert r["colNames"] == lost_cols, (
        "the Lost board drew %s; the reason columns are %s" % (r["colNames"], lost_cols))
    assert r["columns"] == len(lost_cols), (
        "the Lost board matched `class=\"col` %s times; expected %s reason columns and no + New "
        "button, because a bid cannot be started on the tab of dead ones"
        % (r["columns"], len(lost_cols)))
    assert r["colNames"] != rendered["stages"], "the Lost board drew the pipeline columns"
    for held in ("Project on Hold", "Small Bid <$25k - Pending"):
        assert held not in r["colNames"], (
            "%r is a Lost column, but a bid on hold is still live" % held)
    assert r["cards"] == 3, "the Lost board drew %s cards; the fixture has 3" % r["cards"]


# ── the Handed Off tab, which since 2026-08-28 is what winning no longer does ──
# Hanz, 2026-08-28: "Once we receive the Contact Info, we indicate it as handed off... Then the Won
# category would be relabeled as 'Handed Off'. After the Handed Off Pipeline would just be one list."
@needs_node
def test_the_handed_off_tab_draws_one_flat_column(rendered):
    """A THIRD column vocabulary through the same kanbanHtml, and the shortest one the page has.

    This replaces two tests that asserted the FOUR outstanding-work columns of the Won tab, which
    existed from 2026-08-20 to 2026-08-28. That tab needed columns precisely because winning took a
    card OFF the live board: the deposit and the contacts still owed on the job had to stay visible
    somewhere, so the tab re-answered "what is left to do" away from the board. Winning no longer
    moves anything, so that question is answered where the work is — in the pipeline's own
    Won/Approved, Deposit received and Contact info columns — and what is left here is a record of
    finished jobs. Grouping a finished list invites the reader to believe the groups mean work, so
    there is one column, and the only thing it claims is the one thing true of every card under it.

    Asserted against crm-core's own HANDOFF_COLS and against the pipeline it must not be, so a
    hand-off branch quietly falling through to STAGES fails here rather than on screen. An empty tab
    renders trivially and proves nothing, so the fixture lands a card by both routes into it: a job
    that went the whole distance, and one won on the phone off a bid nobody sent — the second has no
    portal fields at all, which is what makes it the row that catches a rule reading deposit or
    contacts before it reads `handed_off_at`."""
    r = rendered["results"]["handed_off/board"]
    handoff_cols = rendered["handoffCols"]
    assert len(handoff_cols) == 1, (
        "C.HANDOFF_COLS is %s — one flat column IS the tab; a Handed Off board that grew columns "
        "back needs reading before the assertions below mean anything" % handoff_cols)
    assert r["colNames"] == handoff_cols, (
        "the Handed Off board drew %s; C.HANDOFF_COLS is %s" % (r["colNames"], handoff_cols))
    assert r["colNames"] != rendered["stages"], "the Handed Off board drew the pipeline columns"
    assert r["columns"] == len(handoff_cols), (
        "the Handed Off board matched `class=\"col` %s times; expected %s column and no + New "
        "button, because nothing new starts on the tab of finished work"
        % (r["columns"], len(handoff_cols)))
    assert r["cards"] >= 2, (
        "the Handed Off board drew %s cards — the fixture is supposed to land two here, or this "
        "whole test is asserting that an empty tab renders" % r["cards"])
    under = r["byCol"][handoff_cols[0]]
    # Approved, deposit in, contacts in, then handed over: the ordinary way a job leaves the board.
    assert "handoff-1" in under, (
        "a handed-off job is not under the one column: %s" % r["byCol"])
    # Won on the phone off an unsent bid and passed straight to operations. It has no portal state
    # whatsoever, so a rule that reads the deposit or the contacts first loses this card entirely —
    # and it is also the proof that the tab is not merely the far end of the pipeline.
    assert "handoff-2" in under, (
        "the handed-off UNSENT bid is not under the one column: %s" % r["byCol"])


@needs_node
def test_a_won_job_stays_on_the_live_board_until_somebody_hands_it_off(rendered):
    """This assertion INVERTED on 2026-08-28, and the inversion is the product change.

    From 2026-08-20 these two rows had to be GONE from Active. Eight days of it showed why that was
    wrong: a won job still owes a deposit and a set of contacts, and the sales meeting is run off the
    Active board — so taking the card away the moment somebody said "we won it" hid the remaining
    work from the very people chasing it. Winning is now a COLUMN on that board, and the only thing
    that removes a card is a human pressing Hand it off.

    Both routes to won are checked, because they reach the board through different fields: one
    derived from the deposit landing, one marked by hand on a bid nobody has sent. The hand-off rows
    are checked in the other direction — if they linger, the button does nothing and the board never
    empties.

    Staying put is only half right, so the old Trabon complaint is asserted here too — "I marked
    Trabon Group project as Won but it's still in the Created but Not Sent bucket". The card has to
    MOVE as well as stay: it belongs with the approved work, not in the column for bids nobody has
    sent. Named off the fixture rather than off the heading string, so renaming a column in crm-core
    stays a one-line change there."""
    active = rendered["results"]["active/board"]["poolIds"]
    for pid in ("won-hand-1", "received-1"):
        assert pid in active, (
            "%s was won and has left the Active board — winning stopped moving cards off it on "
            "2026-08-28, because the deposit and contacts owed on a won job are still live work: %s"
            % (pid, active))
    for pid in ("handoff-1", "handoff-2"):
        assert pid not in active, (
            "%s has been handed off and is still on the Active board — pressing that button is the "
            "one thing that clears a card now: %s" % (pid, active))
    by_col = rendered["results"]["active/board"]["byCol"]
    assert "won-hand-1" not in by_col[rendered["stages"][0]], (
        "the bid marked won by hand is back in the %r column, which is the Trabon complaint that "
        "the won mark outranking not_sent was written to settle" % rendered["stages"][0])
    approved = [c for c, ids in by_col.items() if "approved-1" in ids]
    assert len(approved) == 1, (
        "the plainly-approved fixture row is in %s columns, so there is no column left to name the "
        "hand-won bid against" % len(approved))
    approved_col = approved[0]
    assert "won-hand-1" in by_col[approved_col], (
        "the bid marked won by hand did not file with the approved work (%r) — it drew under %s"
        % (approved_col, [c for c, ids in by_col.items() if "won-hand-1" in ids]))


@needs_node
def test_every_row_in_the_pool_becomes_a_card(rendered):
    """A card silently dropped by C.group (an unknown stage) is invisible on screen and looks like
    a data problem. C.groupHandedOff cannot drop one — it takes every item it is handed straight
    into its single column, deliberately, rather than re-deriving who belongs there — so on that tab
    this reads as a check that the pool and the render agree about how many cards there are."""
    for tab in TABS:
        r = rendered["results"]["%s/board" % tab]
        assert r["cards"] == r["pool"], (
            "the %s board drew %s cards for %s rows — some were dropped"
            % (tab, r["cards"], r["pool"]))


@needs_node
def test_the_pools_partition_every_row(rendered):
    """The four tabs PARTITION the data (boardPool says so in as many words). Every fixture row on
    exactly one tab: a row on none is reachable from nowhere, a row on two is double-counted by the
    pills above the board."""
    seen = {}
    for tab in TABS:
        for pid in rendered["results"]["%s/board" % tab]["poolIds"]:
            seen.setdefault(pid, []).append(tab)
    dupes = {k: v for k, v in seen.items() if len(v) > 1}
    assert not dupes, "rows on more than one tab: %s" % dupes
    missing = [pid for pid in rendered["everyId"] if pid not in seen]
    assert not missing, "rows on no tab at all: %s" % missing


@needs_node
def test_the_new_button_is_only_on_the_live_tabs(rendered):
    """Not on Lost, where it would file a brand-new bid as closed lost; not on Handed Off, where it
    would file one as finished and passed to operations before anybody has sent it."""
    for tab in LIVE_TABS:
        assert rendered["results"]["%s/board" % tab]["newButton"]
    for tab in TABS:
        if tab in LIVE_TABS:
            continue
        assert not rendered["results"]["%s/board" % tab]["newButton"], (
            "+ New is on the %s board, which is not a board a new bid belongs on" % tab)


@needs_node
def test_the_test_chip_appears_only_on_the_lost_board(rendered):
    """Lost holds every dead deal, test ones included, so those cards have to say so. Nowhere else:
    the chip is drawn only inside chipsHtml's isLost branch, and a scratch project that was WON stays
    on the Test tab, where the tab is the label."""
    assert rendered["results"]["lost/board"]["testChip"]
    for tab in TABS:
        if tab == "lost":
            continue
        assert not rendered["results"]["%s/board" % tab]["testChip"]


@needs_node
def test_the_won_chip_draws_on_every_board_a_won_job_reaches(rendered):
    """Three places, three different reasons, and the fixture puts a won card on each.

    ON ACTIVE, both views — and this is the assertion that INVERTED on 2026-08-28. It read `not`
    until then, and the reasoning behind it was that a chip saying "Won" on a card sitting in the
    Created but Not Sent column is a card arguing with the bucket it is in, and the estimator reads
    the bucket. That reading was right about the symptom and wrong about the cause: what disagreed
    was the COLUMN, not the chip. stage() now reads the won mark above not_sent, so the card sits
    under Won/Approved and the two finally say the same thing — which makes the chip nearly
    redundant there and worth keeping anyway, because a card further along (Deposit received,
    Contact info) is also won and its column no longer says so.

    ON TEST: a scratch project that was won stays under Test (boardPool files by is_test before it
    asks anything else), and there the chip is the ONLY thing saying it was won.

    ON HANDED OFF: every card on that tab was won on the way to being handed over, and the single
    column heading says only that we are done — not how the job ended."""
    for view in ("board", "table"):
        assert rendered["results"]["active/%s" % view]["wonChip"], (
            "no Won chip in the %s view of the Active board — a won job lives there again since "
            "2026-08-28, and past the Won/Approved column the chip is the only thing that says a "
            "card was won" % view)
    assert rendered["results"]["test/board"]["wonChip"], (
        "a won TEST project draws no Won chip — on that tab the chip is the only thing saying so")
    assert rendered["results"]["handed_off/board"]["wonChip"], (
        "a handed-off job draws no Won chip — the one column heading does not say it was won")


@needs_node
def test_the_table_view_draws_a_row_per_proposal_plus_its_header(rendered):
    for tab in TABS:
        r = rendered["results"]["%s/table" % tab]
        assert r["rows"] == r["pool"] + 1, (
            "the %s table drew %s <tr> for %s rows plus a header" % (tab, r["rows"], r["pool"]))


# ── what a broken template looks like on screen ──────────────────────────────
@needs_node
@pytest.mark.parametrize("tab,view", COMBOS)
def test_no_raw_template_token_reaches_the_page(rendered, tab, view):
    """A `${…}` in the output means a template literal was built as a plain string somewhere."""
    assert not rendered["results"]["%s/%s" % (tab, view)]["rawToken"]


@needs_node
@pytest.mark.parametrize("tab,view", COMBOS)
def test_the_word_undefined_never_reaches_the_page(rendered, tab, view):
    """The fixture includes a row carrying nothing but an id. A template that assumes a field prints
    the literal "undefined" on a customer-facing board rather than throwing, so nothing catches it
    except looking."""
    assert not rendered["results"]["%s/%s" % (tab, view)]["undefinedLeak"], (
        "the %s view of the %s tab printed \"undefined\" — a row is missing a field a template "
        "assumes" % (view, tab))
