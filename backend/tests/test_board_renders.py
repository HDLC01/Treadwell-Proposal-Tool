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
# close reason, and Won, columned by what is outstanding — so this is stated as "everything else"
# rather than as a list: a fifth tab then lands in here and fails the column-identity assertions
# below out loud, which is the right way for a new tab to reach whoever maintains this file.
LIVE_TABS = tuple(t for t in TABS if t not in ("lost", "won"))


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
    twice, here and in the harness) and the [data-tab] pills portal.html actually ships."""
    assert rendered["tabs"] == TABS, (
        "the harness and this file disagree about portal.js's tab list: %s vs %s"
        % (rendered["tabs"], TABS))
    assert rendered["pills"] == TABS, (
        "portal.html's tab buttons are %s but portal.js declares %s — a tab with no button is "
        "unreachable, and a button with no tab blanks the board"
        % (rendered["pills"], TABS))
    assert "won" in TABS, (
        "the Won tab is gone from portal.js. If that was deliberate, delete the won assertions "
        "below with it; until then this is the tab a won job lands on")
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
    """Six close reasons plus "Not recorded" — one fewer than the pipeline, which is also what
    proves these are different column sets rather than the same one relabelled."""
    r = rendered["results"]["lost/board"]
    assert r["columns"] == 7, "the Lost board drew %s columns; expected 7" % r["columns"]
    assert r["cards"] == 3, "the Lost board drew %s cards; the fixture has 3" % r["cards"]


# ── the Won tab, off the Active board since 2026-08-20 ───────────────────────
# Hanz: "I marked Trabon Group project as Won but it's still in the Created but Not Sent bucket."
@needs_node
def test_the_won_tab_draws_the_outstanding_columns(rendered):
    """A THIRD column vocabulary through the same kanbanHtml — what is still outstanding, not how far
    down the pipeline the job got. Asserted against crm-core's own WON_COLS, and against the pipeline
    it must not be, so a Won branch quietly falling through to STAGES fails here."""
    r = rendered["results"]["won/board"]
    won_cols = rendered["wonCols"]
    assert len(won_cols) == 4, won_cols
    assert r["colNames"] == won_cols, (
        "the Won board drew %s; C.WON_COLS is %s" % (r["colNames"], won_cols))
    assert r["colNames"] != rendered["stages"], "the Won board drew the pipeline columns"


@needs_node
def test_the_won_tab_is_not_rendered_empty(rendered):
    """An empty tab renders trivially and proves nothing, so the fixture puts a card on this one by
    BOTH routes into it — and in three different columns, so a Won board with one column collapsed
    onto another cannot render identically to a correct one.

    The columns are named POSITIONALLY off C.WON_COLS rather than by string, so renaming a heading is
    a one-line change in crm-core and not a rewrite here; the names in the messages are the current
    ones, for whoever reads the failure."""
    r = rendered["results"]["won/board"]
    won_cols = rendered["wonCols"]
    assert len(won_cols) == 4, (
        "C.WON_COLS is %s — this test names its columns by position, so a changed column set needs "
        "reading before the positions below mean anything" % won_cols)
    assert r["cards"] >= 3, (
        "the Won board drew %s cards — the fixture is supposed to land at least three here, or this "
        "whole file is asserting that an empty tab renders" % r["cards"])
    # Marked won by hand, on a bid nobody has sent: the reported card. It carries no deposit or
    # contacts fields at all, so it is also the row a column rule that reads them first misfiles.
    assert "won-hand-1" in r["poolIds"], (
        "a project marked won by hand is not on the Won tab: %s" % r["poolIds"])
    # Won because the deposit arrived — nobody marked it; isWon derives it.
    assert "received-1" in r["poolIds"], (
        "a project won by its deposit arriving is not on the Won tab: %s" % r["poolIds"])
    by_col = r["byCol"]

    def drew(pid):
        """Where the card actually landed, for the failure message — a bare "not in" says nothing
        about which column swallowed it."""
        return [c for c, ids in by_col.items() if pid in ids]

    assert "won-hand-1" in by_col[won_cols[0]], (
        "the unsent won bid drew under %r, not \"Won before approval\" — a column rule that reads "
        "the deposit before asking whether the customer approved files it under an invoice that "
        "does not exist" % drew("won-hand-1"))
    # Money genuinely out on a job somebody won on the phone. This is the card the old "keep won
    # cards on the live board" argument was protecting, and the column is the whole mitigation for
    # moving it: if it draws anywhere else, the work on it has been made invisible by the move.
    assert "won-hand-2" in by_col[won_cols[1]], (
        "the won job with its deposit still outstanding drew under %r, not \"Deposit outstanding\""
        % drew("won-hand-2"))
    assert "received-1" in by_col[won_cols[3]], (
        "the settled job drew under %r, not \"Complete\"" % drew("received-1"))


@needs_node
def test_a_won_job_is_off_the_live_board(rendered):
    """The point of the tab. Both won rows have to be GONE from Active — the bug was a card that said
    Won sitting in the Created but Not Sent column."""
    active = rendered["results"]["active/board"]["poolIds"]
    for pid in ("won-hand-1", "received-1"):
        assert pid not in active, (
            "%s is still on the Active board after being won: %s" % (pid, active))


@needs_node
def test_every_row_in_the_pool_becomes_a_card(rendered):
    """A card silently dropped by C.group (an unknown stage) is invisible on screen and looks like
    a data problem. C.groupWon has the same exposure on the Won tab, and its `||` fallback means a
    dropped card would land in the wrong column rather than throw."""
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
    """Not on Lost, where it would file a brand-new bid as closed lost; not on Won, where it would
    file one as already won before anybody has sent it."""
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
def test_the_won_chip_survived_the_move_to_its_own_tab(rendered):
    """Three places, three different reasons, and the fixture puts a won card on each.

    ON WON, both views: the columns there answer "what is left to do", so the chip is the only thing
    on the card saying why the card is on that board at all.

    ON TEST: a scratch project that was won stays under Test (boardPool checks is_test before isWon),
    and there the chip is the ONLY thing saying it was won.

    NOT ON ACTIVE: this is the bug the tab replaced. A chip reading "Won" on a card sitting in the
    Created but Not Sent column is a card arguing with the bucket it is in, and the estimator reads
    the bucket."""
    for view in ("board", "table"):
        assert rendered["results"]["won/%s" % view]["wonChip"], (
            "no Won chip in the %s view of the Won tab" % view)
    assert rendered["results"]["test/board"]["wonChip"], (
        "a won TEST project draws no Won chip — on that tab the chip is the only thing saying so")
    assert not rendered["results"]["active/board"]["wonChip"], (
        "a Won chip is still drawing on the Active board — a chip cannot argue with a column, "
        "which is the bug the Won tab replaced")


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
