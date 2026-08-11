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

The three pools PARTITION the rows, and that property is worth more than any single assertion here:
it is what makes the three badges add up, and what guarantees no proposal can fall between them.
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
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── what each tab holds, run for real ────────────────────────────────────────
@needs_node
def test_the_lost_tab_holds_the_lost_projects(ran):
    """The whole ask, in one assertion."""
    assert set(ran["pools"]["lost"]) == {"lost-price", "lost-test", "lost-noreason",
                                         "lost-unknown"}


@needs_node
def test_a_lost_project_is_off_both_live_tabs(ran):
    """His 2026-08-10 constraint, still enforced: a dead deal must not clutter live work."""
    for tab in ("active", "test"):
        assert not [i for i in ran["pools"][tab] if i.startswith("lost-")], (
            "a closed-lost proposal is back on the %s tab" % tab)


@needs_node
def test_a_lost_TEST_project_is_under_lost_and_not_under_test(ran):
    """Test has always excluded lost rows. Excluding them from Lost as well would make the row
    reachable from nowhere at all and the tab's count wrong."""
    assert "lost-test" in ran["pools"]["lost"]
    assert "lost-test" not in ran["pools"]["test"]


@needs_node
def test_the_three_tabs_partition_every_proposal(ran):
    """The property the badges depend on: each row in exactly one pool, and every row in one.

    Mutation this kills: making Lost `isLost(p) && !isTest(p)`, which silently strips the lost
    test projects out of the only tab that would have shown them."""
    pools = ran["pools"]
    seen = pools["active"] + pools["test"] + pools["lost"]
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
