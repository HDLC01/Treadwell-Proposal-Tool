"""The Active Projects board: lost proposals leave it, and test ones get their own tab.

WHAT HANZ ASKED FOR, 2026-08-10.

    "In The Customer CRM allow for the projects to be lost even its been approved and if its
    lost remove it from the Customer CRM. To remove clutter"

    "Active Proposals should have 2 categories one for the Test categories in the projects and
    one for the Active ones."

Asked how the lost ones should still be reachable, he chose: "Gone from the board, but keep a
count somewhere." So NOT a Lost column and NOT the "Show closed lost (N)" toggle under a new name.

THEN, 2026-08-12: "Actualy create another tab for 'Lost' This is where the lost projects will be
held." The count became a THIRD TAB. His original constraint is untouched — a dead deal still takes
up no room on a board of live work — and what it replaced was a link to /projects.html that could
not filter to the lost ones, because that page lists our own drafts and has never heard of
`closed_lost`. The count was honest; the destination was not.

WHAT WAS THERE BEFORE, AND WHY IT IS WORTH A TEST THAT IT IS GONE.

`SHOW_LOST` was a sessionStorage-backed toggle that appended `STAGE_LOST` as an eighth kanban
column, and `visible()` filtered lost rows out only while it was off. Four places had to agree:
the toggle, the filter, the chip that rendered the count, and BOARD_SIG. Deleting three of the
four and leaving the fourth is exactly the kind of half-removal that looks finished on screen.
The board would simply stop repainting when something changed, because BOARD_SIG still held a
variable nothing could move.

THE TABS ARE THE SAME TRI-STATE AS THE PROJECTS PAGE, AND THAT IS THE WHOLE POINT.

`is_test` is true / false / absent (see `_tribool` in drafts.py). A hand-filed `false` has to
BEAT the name heuristic, or un-filing a project genuinely called "Test Treadwell" bounces it
straight back into Test with no way out. Absent means nobody has said, and the name decides.

A second, subtly-different copy of that rule on this page would be worse than useless: a project
Kyle filed as test on the Proposals Database would sit on the Active board as live work, and
nothing on either screen would explain why. So the predicate moved into crm-core.js and is
exercised here under node, and the name heuristic is compared character for character against
the copy projects.js still carries.

THE FLAG HAS TO BE FETCHED, TOO. The board reads /api/portal/pipeline, which proxies the
portal's own pipeline, and the portal has never heard of a test project. The ids match
(`proposal_id` IS the draft id, the identity `_deposit_requested` already relies on), so the
proxy stamps the flag on server-side from ONE drafts read. Doing it per row, or guessing from
the project name in the browser, are the two wrong answers.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
CORE = FRONTEND / "js" / "crm-core.js"
PORTAL_HTML = (FRONTEND / "portal.html").read_text(encoding="utf-8")


def _src(name: str) -> str:
    return (FRONTEND / "js" / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """Source with // comment lines stripped.

    These files explain a bug by quoting it, so a raw grep matches its own prose: portal.js
    still SAYS "there is no SHOW_LOST here any more", and asserting the removal against the raw
    text would fail on that sentence. Same helper as test_no_blink_live_refresh.py.
    """
    return "\n".join(l for l in _src(name).splitlines() if not l.strip().startswith("//"))


def _braced(src: str, i: int, what: str) -> str:
    """src from the `{` at or after i to its match.

    Brace-counted, not regex'd, so a template literal containing a brace cannot truncate the
    block and quietly make an assertion vacuous.
    """
    i = src.index("{", i)
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    pytest.fail("unbalanced braces reading %s" % what)


def _block(name: str, fn: str) -> str:
    """The body of a top-level `function fn(...) {` in js/<name>.

    Every assertion below is scoped through this. Grepping the whole file for a guard name is
    how an earlier test in this repo passed while one panel was broken: another panel used the
    same string, so the name was present and nothing checked WHERE.
    """
    src = _code(name)
    m = re.search(r"\n\s{2,6}(?:async\s+)?function " + re.escape(fn) + r"\s*\(", src)
    assert m, "%s() is gone from %s: these tests need rewriting, not deleting" % (fn, name)
    return _braced(src, m.end(), "%s() in %s" % (fn, name))


def _handler(name: str, needle: str) -> str:
    """The callback body bound at `needle` in js/<name>.

    wireToolbar is an IIFE, so _block cannot reach inside it, and it binds eight controls in
    one function. A whole-function grep for renderBoard() there proves nothing: the view
    toggle, Clear and the sort direction button all call it, so the tab handler can be gutted
    and the name is still present.
    """
    src = _code(name)
    assert needle in src, "%s is not bound in %s" % (needle, name)
    return _braced(src, src.index(needle), "the callback at %s in %s" % (needle, name))


def _sig(name: str, fn: str) -> str:
    """The JSON.stringify([...]) signature literal inside fn."""
    body = _block(name, fn)
    start = body.index("JSON.stringify")
    return body[start:body.index("])", start) + 2]


# ── Change A: closed lost leaves the board ───────────────────────────────────
def test_the_live_tabs_have_no_lost_column():
    """Mutation this kills: putting STAGE_LOST back as an eighth column on the live board, which is
    the shape Hanz explicitly turned down.

    The Lost TAB is a different thing and does not use STAGE_LOST at all: its columns are the close
    REASONS, because every card on it has the same stage and grouping by that would give one tall
    column answering nothing."""
    code = _code("portal.js")
    assert "STAGE_LOST" not in code, (
        "the Closed lost column is back; lost proposals are meant to leave the board")
    kanban = _block("portal.js", "kanbanHtml")
    assert "concat" not in kanban, "kanbanHtml is appending a column again"
    assert "C.group(items, STAGES)" in kanban, (
        "the columns are no longer just STAGES, so something else can slip in")


def test_the_show_closed_lost_toggle_is_gone_including_its_stored_state():
    """All four places had to go together. A leftover sessionStorage key is the harmless-looking
    one, and it is the one that would let a stale session resurrect the old behaviour."""
    code = _code("portal.js")
    for name in ("SHOW_LOST", "LOST_KEY", "tw_crm_lost", "syncLostChip"):
        assert name not in code, "%s survived the removal" % name
    assert "Show closed lost" not in PORTAL_HTML, "the toggle's markup is still in the page"
    assert "tw-lost " not in PORTAL_HTML and 'class="tw-clear tw-lost"' not in PORTAL_HTML, (
        "the toggle button is still in the toolbar")


def test_lost_proposals_are_off_the_live_tabs_and_one_place_decides():
    """`visible()` used to end in a ternary on SHOW_LOST, so the board and the filter dropdowns
    could disagree about what existed. The whole question now lives in boardPool: the tab decides
    the pool, and no toggle can put a dead deal back among live work.

    NOT "filtered out unconditionally" any more — on the Lost tab they are the only rows. What
    survives is that no OTHER tab can show one."""
    pool = _block("portal.js", "boardPool")
    assert "!isLost(p)" in pool, "boardPool no longer excludes closed-lost proposals"
    assert 'TAB === "lost"' in pool, "boardPool has no Lost branch, so that tab renders empty"
    # The lost branch must RETURN before the live filter, or `isTest(p) === (TAB === "test")`
    # judges the Lost tab too and half the dead deals vanish from it.
    assert pool.index('TAB === "lost"') < pool.index("!isLost(p)"), (
        "the live filter runs before the lost branch, so the Lost tab is filtered by is_test")
    vis = _block("portal.js", "visible")
    assert "boardPool()" in vis, "visible() bypasses the pool, so it can show lost rows again"
    assert "isLost" not in vis, (
        "visible() is deciding about lost rows on its own again, which is how the board and the "
        "dropdown counts drifted apart before")


def test_both_filter_dropdowns_count_the_same_pool_the_board_draws():
    """A period or an estimator whose only proposals are lost (or on the other tab) must not be
    offered: picking it empties the board and reads as a broken filter.

    populateMonths became populatePeriods on 2026-08-12 when the dropdown grew weeks alongside
    months. The claim is unchanged — whatever fills that select counts the pool the board draws."""
    for fn in ("populateEstimators", "populatePeriods"):
        body = _block("portal.js", fn)
        assert "boardPool()" in body, "%s still counts every row, lost ones included" % fn
        assert "ALL.forEach" not in body, "%s is back on the unfiltered list" % fn


def test_the_lost_count_is_its_own_tab_and_the_dead_end_link_is_gone():
    """The tab replaced the link. Both halves are asserted: leaving the link beside the tab would
    give two routes to the same rows, one of which lands on a page that cannot filter to them."""
    assert 'data-tab="lost"' in PORTAL_HTML, "there is no Lost tab in the markup"
    assert "lostCount()" in _block("portal.js", "syncTabs"), (
        "the Lost tab never reads how many there are")
    code = _code("portal.js")
    for gone in ("syncLostLink", "crm-lost", "tw-lostlink"):
        assert gone not in code and gone not in PORTAL_HTML, (
            "%s survived, so the dead-end link is still on the page beside the tab that replaced "
            "it" % gone)


def test_every_tab_prints_the_number_it_holds():
    """Mutation this kills: dropping the count out of the pill, or counting one tab's rows into
    another's badge. The badge is the only thing saying whether a tab is worth opening."""
    body = _block("portal.js", "syncTabs")
    assert "lost: lostCount()" in body, "the Lost badge is not the count of lost proposals"
    assert re.search(r"c\.textContent = n\[b\.dataset\.tab\]", body), (
        "the badge is not filled from the per-tab counts, so a pill can advertise a wrong number")
    # The live counts come off `live` (lost already removed), so Active + Test + Lost is every row.
    assert "ALL.filter((p) => !isLost(p))" in body, (
        "the Active/Test counts include lost rows, so the three tabs sum to more than exist")


def test_the_count_is_out_of_what_THIS_TAB_holds():
    """Mutation this kills: `const shown = ALL.length` for the denominator. It reads as
    "3 of 40" with 37 rows apparently hidden by a filter, when 37 is every lost proposal plus
    the whole other tab and no amount of clearing brings them back. It survives every other
    assertion here because ALL.length is what this line said before the change."""
    body = _block("portal.js", "renderBoard")
    assert re.search(r"const shown = boardPool\(\)\.length", body), (
        "the 'N of M' count is out of rows this tab will never show")


def test_the_lost_count_is_in_the_board_signature():
    """It is painted OUTSIDE the board's innerHTML, and lost rows are excluded from everything
    else the signature is derived from. Leave it out and the number freezes at whatever it was
    on first paint, under a guard that looks correct."""
    assert "lostCount()" in _sig("portal.js", "renderBoard"), (
        "the lost count is not in BOARD_SIG, so marking a proposal lost would not update it")


def test_the_tabs_are_painted_under_the_signature_guard():
    """Same reason populateEstimators/populateMonths sit below it: work done before the
    compare-and-return runs on every 25s poll whether or not anything moved. syncTabs paints the
    three counts, which is the job the retired lost link used to have."""
    body = _block("portal.js", "renderBoard")
    assert body.index("BOARD_SIG) return") < body.index("syncTabs()")


def test_a_lost_proposal_can_still_be_reactivated():
    """Reachable from the Lost tab now, as well as by URL from an old notification. Reactivate is
    the only way back onto a live tab, so the drawer has to keep handling a lost row."""
    panel = _block("portal.js", "followupPanelHtml")
    assert 'id="fu-reopen"' in panel, "the Reactivate button is gone"
    assert "isLost(p)" in panel, "the panel no longer knows a lost proposal when it sees one"
    wire = _block("portal.js", "wireFollowup")
    assert '$("fu-reopen")' in wire, (
        "Reactivate is rendered but not wired, so it silently does nothing")
    assert re.search(r'status:\s*"active"', wire), "Reactivate posts something other than active"


# ── Change B: the Active / Test tabs ─────────────────────────────────────────
def test_the_tabs_exist_and_active_is_the_default():
    """Test and Lost are both somewhere you go on purpose. Defaulting to either, or to "all"
    (which would put scratch work back among customer bids), is the failure this pins."""
    code = _code("portal.js")
    assert re.search(r'let TAB = TABS\.includes\(ss\(TAB_KEY, ""\)\)', code), (
        "TAB is no longer validated against the known tabs")
    assert re.search(r': "active"', code), (
        "TAB does not fall back to active for a session that has never chosen")
    # An UNKNOWN stored value has to fall back too: a stale session holding a tab that no longer
    # exists would otherwise paint no pressed pill over an empty board.
    assert 'const TABS = ["active", "test", "lost"]' in code, (
        "the tab list is not one named set, so the stored value and the markup can drift")
    for t in ("active", "test", "lost"):
        assert 'data-tab="%s"' % t in PORTAL_HTML, "the %s tab is not in the markup" % t
    assert re.search(r'data-tab="active" aria-pressed="true"', PORTAL_HTML), (
        "Active is not the tab that reads as selected before the first paint")


def test_the_tab_is_remembered_like_the_rest_of_the_view_state():
    """Every other control on this board survives opening a project and coming back. A tab that
    forgot would silently drop a rep back into Active mid-scan."""
    code = _code("portal.js")
    assert 'TAB_KEY = "tw_crm_tab"' in code
    assert re.search(r"ssSet\(TAB_KEY,", code), "the chosen tab is never stored"


def test_the_tab_is_in_the_board_signature():
    """Without it, clicking Test changes TAB, renderBoard computes an identical signature and
    returns, so the board keeps showing Active and the click looks broken."""
    assert re.search(r"\bTAB\b", _sig("portal.js", "renderBoard")), (
        "TAB is not in BOARD_SIG, so switching tab would not repaint")


def test_the_tab_counts_come_off_the_same_predicate_the_board_filters_with():
    """A tab advertising 3 and then showing 2 is worse than no number at all. Both have to be
    isTest, and both have to drop the lost rows first."""
    body = _block("portal.js", "syncTabs")
    assert "isLost(p)" in body, "the counts include closed-lost proposals the board won't show"
    assert body.count("isTest") == 2, "the counts are not both derived from isTest"


def test_the_board_splits_by_the_FLAG_not_by_the_project_name():
    """portal.js must not grow a second copy of the heuristic. Two copies is how the two pages
    end up disagreeing about the same project, with nothing on screen to explain it."""
    pool = _block("portal.js", "boardPool")
    assert "isTest(p)" in pool, "boardPool does not consult the test flag at all"
    assert "bugtest" not in _src("portal.js"), (
        "portal.js has its own name regex; the rule belongs in crm-core.js so both pages share it")
    # Asserted as a DESTRUCTURING, not by character offset. This was `in _src(...)[:2000]`, which
    # says "isTest appears near the top" — a proxy for "it is imported" that breaks the moment
    # anybody adds a comment above the imports. One did (the note explaining the STAGE_CREATED
    # outage) and this failed at 2128 characters while the code was perfectly correct. A test that
    # counts characters to infer structure will keep crying wolf.
    assert re.search(r"const \{[^}]*\bisTest\b[^}]*\} = C;", _src("portal.js"), re.S), (
        "isTest is not destructured off crm-core, so portal.js is deciding what a test project is "
        "on its own")


def test_the_test_rows_go_to_the_TEST_tab_and_the_others_to_ACTIVE():
    """Which way round, not merely "isTest is consulted". Two mutations survive every other
    assertion in this file:

        isTest(p) !== (TAB === "test")     swaps the tabs. Kyle's scratch work sits under
                                          Active among customer bids and Cedar Ridge sits
                                          under Test, which is worse than no split at all.
        (isTest(p) || true)                ignores TAB. Both tabs show everything, and the
                                          badges still differ, so it reads as working.

    Pinned as the expression because boardPool closes over TAB and ALL. C.isTest is lifted out
    and run under node below; the direction it is applied in only exists here."""
    pool = _block("portal.js", "boardPool")
    assert re.search(r'isTest\(p\)\s*===\s*\(TAB\s*===\s*"test"\)', pool), (
        "boardPool no longer sends exactly the test rows to the Test tab")


def test_the_tabs_are_repainted_by_renderBoard_and_not_only_at_boot():
    """Mutation this kills: deleting `syncTabs()` from renderBoard. wireToolbar calls it once so
    a remembered Test tab reads as selected before the first fetch, and that call is what makes
    the deletion invisible: the pills still render, they just never move again. Click Test and
    the cards change while Active stays pressed and both badges stay on the 0 the markup ships.

    Below the compare-and-return for the same reason populateEstimators is: this runs on a 25s
    poll and must not touch the DOM when nothing moved."""
    body = _block("portal.js", "renderBoard")
    assert "syncTabs()" in body, "the tab pills and their counts are never repainted"
    assert body.index("BOARD_SIG) return") < body.index("syncTabs()")


def test_each_pill_shows_ITS_OWN_count():
    """Mutation this kills: `n.active` in place of `n[b.dataset.tab]`, so both pills print the
    Active number. The counts are still both derived from isTest and still drop the lost rows,
    so test_the_tab_counts_come_off_the_same_predicate_the_board_filters_with passes."""
    body = _block("portal.js", "syncTabs")
    assert "n[b.dataset.tab]" in body, "the two pills would advertise the same number"


def test_clicking_a_tab_changes_it_stores_it_and_repaints():
    """TAB being in BOARD_SIG only helps if something calls renderBoard. Gut this callback and
    the click is inert: the board stays on Active for the whole session and no assertion above
    notices, because the view toggle bound three lines below calls renderBoard() and ssSet()
    too, and test_the_tab_is_remembered_like_the_rest_of_the_view_state greps the whole file."""
    assert 'if (tabs) tabs.addEventListener("click"' in _code("portal.js"), (
        "the Active/Test row is not wired, or is wired behind a condition")
    body = _handler("portal.js", 'tabs.addEventListener("click"')
    assert "TAB =" in body, "the click never changes which tab is current"
    assert "ssSet(TAB_KEY," in body, "the chosen tab is not remembered from the click itself"
    assert "renderBoard()" in body, "the click moves TAB but never repaints, so nothing happens"


def test_the_tab_row_the_js_binds_to_is_the_one_in_the_page():
    """Rename that container on either side and the whole feature goes quiet without throwing:
    $("crm-tabs") returns null, syncTabs and the click binding both return early, and the board
    is stuck on whatever TAB booted as. data-tab is still in the markup, so
    test_the_tabs_exist_and_active_is_the_default passes."""
    assert 'id="crm-tabs"' in PORTAL_HTML, "the tab row lost the id portal.js looks up"
    code = _code("portal.js")
    assert 'const tabs = $("crm-tabs")' in code, "the toolbar no longer binds the tab row"
    assert '$("crm-tabs")' in _block("portal.js", "syncTabs"), (
        "syncTabs paints some other element")


def test_clearing_the_filters_does_not_throw_you_off_the_tab():
    """Clear narrows-down state. Which board you are looking at is not that, any more than the
    board/table view is."""
    src = _src("portal.js")
    i = src.index('clear.addEventListener("click"')
    body = src[i:i + 700]
    assert "TAB" not in body, "✕ Clear resets the tab, so it drops you out of Test"
    assert "VIEW" not in body


# ── the shared predicate, run for real under node ────────────────────────────
needs_node = pytest.mark.skipif(shutil.which("node") is None,
                                     reason="node is not installed")


def _run(script: str):
    prelude = ("const C = require(%s);\n"
               "const out = (v) => console.log(JSON.stringify(v));\n" % json.dumps(str(CORE)))
    proc = subprocess.run(["node", "-e", prelude + script],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _is_test(row):
    return _run("out(C.isTest(%s));" % json.dumps(row))


@needs_node
@pytest.mark.parametrize("row,expect,why", [
    ({"project_name": "Cedar Ridge Distribution Center"}, False, "a real bid nobody has filed"),
    ({"project_name": "Test Will 7/29"}, True, "nobody has filed it, so the name decides"),
    ({"project_name": "Lock Test"}, True, "the name decides"),
    ({"project_name": "Demolition of Bldg C"}, False,
     "'demo' inside 'demolition' must NOT match: a construction tool full of demolition jobs"),
    ({"project_name": "zz old numbers"}, True, "the zz prefix people use to sink a row"),
    ({"project_name": "Oak Grove - delete me"}, True, "the phrase, not a word boundary"),
    ({"project_name": "Cedar Ridge", "is_test": True}, True, "filed as test by hand"),
    ({"project_name": "Test Treadwell", "is_test": False}, False,
     "THE one that matters: a hand-filed false has to beat the name heuristic"),
    ({"project_name": "Test Treadwell", "is_test": None}, True,
     "null is 'nobody has said', not 'said no', so the name gets its vote back"),
])
def test_the_tri_state_is_honoured_the_way_the_projects_page_honours_it(row, expect, why):
    assert _is_test(row) is expect, why


@needs_node
def test_a_string_flag_is_not_mistaken_for_a_decision():
    """The flag reaches the browser through PostgREST's `data->>is_test`, which is TEXT. The
    backend coerces it (`_tribool`), but if that ever regresses, `typeof === "boolean"` means a
    stray "false" falls back to the name rather than being read as a decision, and never as
    the truthy string that "false" is in JavaScript."""
    assert _is_test({"project_name": "Cedar Ridge", "is_test": "false"}) is False
    assert _is_test({"project_name": "Test Treadwell", "is_test": "false"}) is True


def test_the_name_heuristic_is_character_identical_to_the_one_projects_js_uses():
    """Two copies exist: projects.js predates crm-core.js and was being edited by somebody else
    the day this moved. They must agree exactly: a project under Test on the Proposals Database
    has to be under Test here, and "nearly the same regex" is precisely how that breaks.

    Widening either one is the trap. "demo" lives inside "demolition"; a misfiled real bid is
    worse than a visible test project. If you deliberately change the rule, change BOTH.
    """
    def literals(src: str) -> list:
        m = re.search(r"function nameLooksLikeTest\(p\) \{(.*?)\n\s*\}", src, re.S)
        assert m, "nameLooksLikeTest() moved or was renamed"
        return re.findall(r"/(?:[^/\\\n]|\\.)+/i", m.group(1))

    theirs = literals(_src("projects.js"))
    mine = literals(_src("crm-core.js"))
    assert theirs, "projects.js no longer has a name heuristic; this test's reference has moved"
    assert mine == theirs, (
        "the two heuristics have drifted:\n  projects.js: %s\n  crm-core.js: %s" % (theirs, mine))


# ── the flag has to reach the board: the pipeline proxy ──────────────────────
def _row(pid="p1", **kw):
    """A pipeline row shaped the way the portal actually sends one."""
    base = {"proposal_id": pid, "project_name": "Oak Grove", "customer_email": "dave@x.com",
            "proposal_status": "sent", "deposit_status": "pending",
            "schedule_status": "pending", "contacts_status": "pending", "unread": 0,
            "sent_at": "2026-08-01T12:00:00+00:00"}
    base.update(kw)
    return base


def _wire(monkeypatch, rows, projects, calls=None):
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": rows})

    def list_drafts(*a, **k):
        if calls is not None:
            calls.append(1)
        return projects
    monkeypatch.setattr(main.drafts, "list_drafts", list_drafts)


def _pipeline():
    r = client.get("/api/portal/pipeline")
    assert r.status_code == 200, r.text
    return {p["proposal_id"]: p for p in r.json()["proposals"]}


def test_the_proxy_stamps_our_test_flag_onto_the_portals_rows(monkeypatch):
    """The portal has no `is_test` column and never will: it does not own the concept. Without
    this the board would have to guess from the name, which throws away every hand-filed
    decision Kyle has made on the Projects page."""
    _wire(monkeypatch, [_row("p1"), _row("p2")],
          [{"id": "p1", "is_test": True}, {"id": "p2", "is_test": False}])
    out = _pipeline()
    assert out["p1"]["is_test"] is True
    assert out["p2"]["is_test"] is False


def test_a_project_nobody_has_filed_is_left_alone_rather_than_called_real(monkeypatch):
    """Stamping False here would be the quiet disaster: it means "somebody confirmed this is a
    real bid", which switches the name fallback off for every legacy row at once."""
    _wire(monkeypatch, [_row("p1")], [{"id": "p1", "is_test": None}])
    assert _pipeline()["p1"].get("is_test") is None


def test_a_proposal_with_no_draft_row_is_not_stamped_at_all(monkeypatch):
    """A trashed project, or one whose draft predates the list window. Absent leaves the
    browser's name heuristic in charge, which is the same treatment a legacy row gets."""
    _wire(monkeypatch, [_row("gone")], [{"id": "p1", "is_test": True}])
    assert "is_test" not in _pipeline()["gone"]


def test_it_is_one_drafts_read_for_the_whole_board_not_one_per_proposal(monkeypatch):
    """60 proposals used to be 60 round-trips waiting to happen. The board polls every 25s."""
    calls = []
    _wire(monkeypatch, [_row("p%d" % i) for i in range(25)],
          [{"id": "p%d" % i, "is_test": False} for i in range(25)], calls)
    _pipeline()
    assert len(calls) == 1, "the flag lookup runs %d times per board load" % len(calls)


def test_an_unreadable_drafts_list_does_not_take_the_board_down(monkeypatch):
    """The split is a nicety; the pipeline is the page. A Supabase blip must cost the tabs their
    accuracy, not cost the rep the board."""
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": [_row("p1")]})
    monkeypatch.setattr(main.drafts, "list_drafts",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("postgrest down")))
    out = _pipeline()
    assert out["p1"]["project_name"] == "Oak Grove"
    assert "is_test" not in out["p1"], "a failed lookup invented a flag"


def test_an_unreachable_portal_still_fails_the_way_it_always_did(monkeypatch):
    """The proxy raised before this change and must keep raising: the board's own catch keeps
    the stale rows on screen and shows the reason, and swallowing the error here would replace
    that with an empty, authoritative-looking board."""
    monkeypatch.setattr(main, "_portal",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("portal offline")))
    with pytest.raises(RuntimeError):
        client.get("/api/portal/pipeline")


def test_the_two_pages_agree_about_the_same_project(monkeypatch):
    """The end-to-end claim, in one test: whatever /api/drafts tells the Proposals Database about
    a project, /api/portal/pipeline tells the Active Projects board about the same project. They
    read the one list, so a disagreement means somebody has started deriving it twice."""
    projects = [{"id": "p1", "project_name": "Test Treadwell", "is_test": False},
                {"id": "p2", "project_name": "Cedar Ridge", "is_test": True}]
    _wire(monkeypatch, [_row("p1", project_name="Test Treadwell"),
                        _row("p2", project_name="Cedar Ridge")], projects)
    board = _pipeline()
    for p in projects:
        assert board[p["id"]]["is_test"] is p["is_test"]


def test_the_tabs_read_active_lost_test():
    """Hanz, 2026-08-15: "Active and Lost should be the beside move the Test to the right most".

    Active and Lost are both real customer work; Test is scratch, so it belongs at the far end.
    Behaviour-neutral — every click resolves through `data-tab` and the badges fill by
    `dataset.tab` — which is why the ORDER is the only thing holding it, and why it needs saying.
    No assertion covered tab order before this one."""
    html = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "portal.html").read_text(
        encoding="utf-8")
    active = html.index('data-tab="active"')
    lost = html.index('data-tab="lost"')
    test = html.index('data-tab="test"')
    assert active < lost < test, "the board tabs are not Active | Lost | Test"
