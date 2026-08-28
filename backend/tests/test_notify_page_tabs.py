"""The Notification Sending page's per-project list: four categories, one project each, paged.

Hanz, 2026-08-19, in three messages about the per-project section:

    "the per project Notification sending should be separate for active and test projects"
    "for it not to populate the per projects tab there should also be a lost, won category for
     that. Where it moves the project to there."
    "add a pagination"

WHAT WAS WRONG. Every project the portal knows about sat in one flat list — somebody's scratch
bid, a deal lost in June, a job finished and paid, and the four proposals a human actually needs
to set recipients on, all in the same scroll. The list only ever grew, and nothing about a row
said which kind it was.

WHY THESE FOUR CATEGORIES, AND WHY IN THIS ORDER. The vocabulary is not new: `crm-core.js` already
decides what a project IS for the CRM board, and this page reads the same predicates so the two
screens cannot disagree.

  * LOST beats TEST, because that is what the board does. crm-core's `stage()` returns Closed lost
    before it looks at anything else, and portal.js's `boardPool` puts a lost test project on the
    Lost tab carrying a Test chip. Two screens disagreeing about where a dead deal lives is worse
    than either answer, so this page copies the board — chip included.
  * TEST beats HANDED OFF, because a test project's outcome is fiction. Handed Off is a number a
    human reads as finished real work, and somebody's scratch bid must not be able to inflate it.
    The board agrees: boardPool files a handed-off test project on its Test tab.
  * ACTIVE is the REMAINDER, never a predicate of its own. That is what makes the four a partition
    and what stops a project the categories don't recognise from being reachable from no tab.

THE FOURTH CATEGORY IS HANDED OFF, NOT WON — CHANGED 2026-08-28, AND THE INVERSION IS WHY HALF THE
ASSERTIONS BELOW READ THE WAY THEY DO.

Until that day, winning filed a job away on both screens: the CRM board moved a won card off Active
onto a Won tab (2026-08-20, "I marked Trabon Group project as Won but it's still in the Created but
Not Sent bucket"), and this page's fourth category matched it. Both halves are now reversed. Won is
a COLUMN on the Active board — "Won/Approved" — a won job stays in the working list, and the one
thing that takes a card out of it is a human pressing Hand it off, which writes `handed_off_at` and
nothing else (see test_hand_it_off.py and test_handed_off_tab.py).

WHY THE PRESS RATHER THAN THE DERIVED STATE. Winning is the customer's decision; being finished with
a job is ours, and between the two sits every piece of work the win creates — the deposit, the
contacts, the schedule, the hand-off to the crew. A page that empties a card out of the list the
moment the customer says yes hides precisely the window in which somebody still owes something.
`won_at` and `approved_at` answer "did they say yes". `handed_off_at` answers "is this off our
list", and only a person can answer that one.

WHAT THAT COSTS THIS FILE, STATED PLAINLY: the five `w-` fixtures below are won by every measure the
old rule used — two of them by hand, one of them never even sent — and every one of them is now
expected under ACTIVE. They are not leftovers waiting to be re-filed. They are the regression this
change exists to prevent, and the day one of them categorises anywhere else is the day the
estimator's working list has quietly started emptying itself again.

WHAT IS UNCHANGED IS THE PRECEDENCE, and it is what this file exists to pin: nothing the board calls
Closed lost can appear under Active here, and nothing it calls Test can either. Both now sit above
Handed Off for the same reasons they sat above Won, and the `l-handed-off` and `t-handed-off`
fixtures are there so that reordering ppCategory fails loudly instead of quietly parking a dead deal
in the one tab nobody goes back to check.

EVERYTHING BELOW IS EXECUTED. The house rule, bought the hard way on 2026-08-12: a source-text
assertion cannot see an unbound identifier, and that class of bug took the board down on prod with
every test green. `js/notify-tabs-harness.js` lifts the real functions out of notifications.js,
runs them against the real crm-core.js and a DOM stub, and reports what actually rendered.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "notify-tabs-harness.js"
PAGE_JS = FRONTEND / "js" / "notifications.js"
PAGE_HTML = FRONTEND / "notifications.html"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── categorisation ───────────────────────────────────────────────────────────
@needs_node
def test_each_category_receives_the_right_projects(ran):
    """The whole ask, in one assertion, off the fixture ids."""
    got = {}
    for pid, cat in ran["categoryOf"].items():
        got.setdefault(cat, set()).add(pid)
    assert got["active"] == {"a-sent", "a-viewed", "a-notsent", "a-approved-owes",
                             "a-approved-submitted", "a-nodeposit-unapproved",
                             "a-testname-real",
                             # WON, AND STILL HERE (2026-08-28). Every one of these five was in the
                             # fourth category until the day winning stopped filing a job away.
                             "w-deposit-in", "w-no-deposit-needed", "w-contacts-in",
                             "w-marked", "w-marked-notsent"}
    assert got["handed_off"] == {"h-derived", "h-marked", "h-notsent"}
    assert got["lost"] == {"l-price", "l-test", "l-was-won", "l-was-marked-won", "l-handed-off"}
    assert got["test"] == {"t-flag", "t-name", "t-won", "t-marked-won", "t-handed-off"}


@needs_node
def test_every_project_lands_in_exactly_one_category_and_none_is_dropped(ran):
    """The property the pills depend on, and the assertion that matters most here: a project
    silently vanishing off this page means somebody's notification recipients become unreachable
    and nobody finds out.

    Mutations this kills: making Active a predicate of its own (`!isLost && !isTest && !isHandedOff`
    reads identically and drops anything a future status makes all three false for), or making
    Lost `isLost(p) && !isTest(p)`, which strips lost test projects out of every tab."""
    cats = ran["categoryOf"]
    assert sorted(cats.keys()) == sorted(ran["everyId"]), (
        "a project got no category at all, so it is reachable from no tab")
    assert set(cats.values()) <= set(ran["tabIds"]), "a category exists with no tab to show it"
    assert sum(ran["counts"].values()) == len(ran["everyId"]), (
        "the four counts do not add up to every project, so a row is being double-counted or lost")


@needs_node
def test_a_lost_test_project_is_lost_not_test(ran):
    """Precedence, matching the board exactly: crm-core's stage() answers Closed lost before it
    looks at anything else, and portal.js puts the same row on its Lost tab. Reversing this pair
    is the mutation that makes the two screens disagree about a dead deal."""
    assert ran["categoryOf"]["l-test"] == "lost"


@needs_node
def test_a_handed_off_test_project_is_test_not_handed_off(ran):
    """A scratch bid's outcome is fiction, and that did not change when the fourth category did.
    Handing a fake job off is housekeeping on a fake job; the Handed Off pill is a number read as
    finished real work, so a test project must not be able to inflate it. The board files the same
    row under Test.

    `t-handed-off` carries BOTH a by-hand win and a hand-off stamp, so it is the row that actually
    exercises the precedence — `t-won` below is only won, and since 2026-08-28 a won project has no
    category of its own to be pulled into."""
    assert ran["boardStage"]["t-handed-off"] == "Won/Approved", (
        "fixture drift: this row is supposed to be one the board agrees was won")
    assert ran["categoryOf"]["t-handed-off"] == "test", (
        "a test project is being counted as Handed Off, so that pill overstates finished work")
    assert ran["depositSatisfied"]["t-won"] is True and ran["categoryOf"]["t-won"] == "test", (
        "a test project won by the deposit landing left the Test tab")


@needs_node
def test_a_project_lost_after_it_was_approved_and_paid_is_still_lost(ran):
    """Money came in and the job died anyway. Lost is above every other answer for the same reason
    it is above Test: the board says Closed lost, and this page must not say otherwise."""
    assert ran["categoryOf"]["l-was-won"] == "lost"
    assert ran["depositSatisfied"]["l-was-won"] is True, (
        "fixture drift: this row is meant to be one the money signal would otherwise claim")


@needs_node
def test_approved_with_the_deposit_still_outstanding_stays_active(ran):
    """The judgement call, pinned, and it long predates the 2026-08-28 rename. These two are the
    most worth-chasing rows on the page — approved, money still outstanding — and the whole reason
    the fourth category is a human press rather than a derived state is that no derivation should be
    able to file them away while somebody still owes something. The board keeps them live too, on
    its Won/Approved and Deposit-submitted columns."""
    for pid in ("a-approved-owes", "a-approved-submitted"):
        assert ran["categoryOf"][pid] == "active", (
            "%s is filed as Won while its deposit is outstanding" % pid)
        assert ran["depositSatisfied"][pid] is False


@needs_node
def test_deposit_satisfied_alone_does_not_take_a_project_off_the_working_list(ran):
    """`a-nodeposit-unapproved` is a no-deposit job emailed this morning that nobody has opened.
    depositSatisfied says True about it, because that predicate answers "is money outstanding",
    not "did we win" and certainly not "are we finished".

    Mutation this kills: routing this page on `C.depositSatisfied`, which is the tempting one-liner
    and would take a proposal nobody has read off the estimator's list."""
    assert ran["depositSatisfied"]["a-nodeposit-unapproved"] is True
    assert ran["categoryOf"]["a-nodeposit-unapproved"] == "active", (
        "an unopened proposal left the working list because it collects no deposit")


@needs_node
def test_winning_by_the_deposit_landing_does_not_take_a_job_off_the_working_list(ran):
    """REVERSED ON 2026-08-28, and this is one of the tests that was exactly backwards. Both rows are
    won by the derived rule — one collected its deposit, one legitimately collects none — and until
    that day both were filed under a Won tab and gone from the estimator's list.

    They stay now. A job whose money question is settled still needs contacts, a schedule and a
    hand-off to the crew, and none of that gets done from a tab nobody opens. The board made the same
    move on the same day: these two sit on its live columns, not on a tab of their own.

    Asserted against crm-core's own verdict rather than off the fixture ids, so "these are genuinely
    won" cannot quietly stop being true while the test carries on passing."""
    for pid, col in (("w-deposit-in", "Deposit received"),
                     ("w-no-deposit-needed", "Won/Approved")):
        assert ran["depositSatisfied"][pid] is True, (
            "fixture drift: %s is meant to be won by the money question being settled" % pid)
        assert ran["boardStage"][pid] == col, (
            "fixture drift: the board columns %s as %r" % (pid, ran["boardStage"][pid]))
        assert ran["categoryOf"][pid] == "active", (
            "%s left the working list on a win alone — only Hand it off may do that" % pid)


@needs_node
def test_a_project_the_portal_moved_past_approval_is_still_in_the_working_list(ran):
    """`proposal_status` is no longer "approved" once contacts land, so this row is as far through
    the portal as a job can travel without a human touching it — which makes it the most tempting row
    on the page to call finished automatically. Nobody has said it is finished. It sits on the
    board's last live column and in this page's working list until someone presses Hand it off.

    Mutation this kills: reaching back for `approved_at` — or any other derived stamp — as the thing
    that empties the list, which is exactly what this page did until 2026-08-28."""
    assert ran["boardStage"]["w-contacts-in"] == "Contact info", "fixture drift"
    assert ran["categoryOf"]["w-contacts-in"] == "active", (
        "a job the portal carried to its last live column was filed away with nobody pressing "
        "anything")


@needs_node
def test_a_project_marked_won_by_hand_stays_in_the_working_list(ran):
    """RENAMED AND REVERSED ON 2026-08-28. This was `..._leaves_the_working_list` and it asserted the
    opposite of what it asserts now — recorded that way round because the product decision changed,
    not because the old test was wrong.

    Hanz, 2026-08-19: "Is there any way to also mark as won for now other than after the deposit has
    been received". That button records the CUSTOMER's answer. It is not the estimator saying they
    are done with the job, and the second row is where the distinction bites: `w-marked-notsent` has
    never been sent, so it has no portal row and no derived progress whatsoever — everything still
    owed on it is owed by us. Filing it away on the strength of the mark would hide a bid that has
    not even gone out yet.

    Cross-checked through stage(), which since 2026-08-28 reads the by-hand mark ahead of the
    pipeline status: "Won/Approved" on a sent row and on an unsent one can only come from `won_at`."""
    for pid in ("w-marked", "w-marked-notsent"):
        assert ran["boardStage"][pid] == "Won/Approved", (
            "fixture drift: %s is meant to be won by the by-hand mark and nothing else" % pid)
        assert ran["depositSatisfied"][pid] is False, (
            "fixture drift: %s is meant to be a row only the manual mark can win" % pid)
        assert ran["categoryOf"][pid] == "active", (
            "%s left the working list on a by-hand win — the mark records the customer's answer, "
            "not that we are finished with the job" % pid)


@needs_node
def test_a_project_marked_won_and_then_lost_is_still_lost(ran):
    """Lost above the win, with the manual mark in play. The two facts are stored independently (see
    drafts.set_won) because a sent project's closed_lost belongs to the portal, which no draft-side
    write can clear — so a cancelled job keeps its `won_at` for ever, and nothing but this precedence
    stops it reading as live work.

    Since 2026-08-28 the win no longer routes this page at all, which makes what this pins narrower
    and more durable: whatever the mark says, Closed lost is the answer."""
    assert ran["categoryOf"]["l-was-marked-won"] == "lost"


@needs_node
def test_a_test_project_marked_won_by_hand_is_still_a_test_project(ran):
    """Test above the win, with the manual mark in play. A human pressing the button says nothing
    about whether the project is real work, so the override must not become a way round the rule that
    keeps somebody's scratch bid out of a number Troy reads as revenue."""
    assert ran["categoryOf"]["t-marked-won"] == "test"


@needs_node
def test_a_handed_off_project_leaves_the_working_list_however_it_was_won(ran):
    """The other half of the 2026-08-28 change, and the only thing that empties this list: a human
    pressed Hand it off, which writes `handed_off_at` and nothing else.

    BOTH ROUTES INTO A WIN ARE HERE ON PURPOSE. `h-derived` was won by the deposit landing and
    carried on through the portal until its contacts came in; `h-marked` was won by the estimator
    pressing the button on a job with no portal progress at all. The page must not care which — a
    hand-off is a statement about US being finished, and a rule that only recognised one route would
    leave half the finished work sitting in the working list for ever.

    Note the board stages below are deliberately DIFFERENT from each other. Neither is what decides
    this, which is the point: the categories no longer read the pipeline at all to answer it."""
    assert ran["boardStage"]["h-derived"] == "Contact info", "fixture drift"
    assert ran["depositSatisfied"]["h-derived"] is True, "fixture drift"
    assert ran["boardStage"]["h-marked"] == "Won/Approved", "fixture drift"
    assert ran["depositSatisfied"]["h-marked"] is False, (
        "fixture drift: h-marked is meant to be won by the by-hand mark alone")
    for pid in ("h-derived", "h-marked"):
        assert ran["categoryOf"][pid] == "handed_off", (
            "%s was handed off and is still in the working list, so the one press that is supposed "
            "to clear a card does nothing" % pid)


@needs_node
def test_a_handed_off_project_that_was_never_sent_still_lands_in_handed_off(ran):
    """An unsent bid has no portal row, so it carries no `approved_at`, no deposit fields and no
    proposal_status — every field a routing rule is tempted to read on the way to an answer. Reach
    for one of them before the hand-off stamp and this row falls out of Handed Off; because Active
    is the remainder rather than a predicate, it does not error, it just silently reappears in the
    working list somebody has already finished with.

    Kyle's case for the by-hand mark is the same case for this one: a bid can be settled, or
    abandoned, entirely off-system, and the estimator still needs a way to say so."""
    assert ran["boardStage"]["h-notsent"] == "Won/Approved", (
        "fixture drift: this row is meant to be unsent and won only by the by-hand mark")
    assert ran["depositSatisfied"]["h-notsent"] is False, "fixture drift"
    assert ran["categoryOf"]["h-notsent"] == "handed_off", (
        "an unsent project that was handed off came back to the working list")


@needs_node
def test_a_project_handed_off_and_then_lost_is_still_lost(ran):
    """Lost above Handed Off, and this is the sharper version of the precedence the file already
    pins for Test, because a hand-off is the LAST thing that happens to a healthy job. Read the
    hand-off stamp first and a cancelled deal sits in Handed Off looking finished — which is the one
    tab nobody goes back to check, so the mistake would never surface as a complaint.

    The board makes the same call: crm-core's stage() answers Closed lost before anything else, and
    portal.js keeps a lost card on its Lost tab whatever else is stamped on it."""
    assert ran["boardStage"]["l-handed-off"] == "Closed lost", "fixture drift"
    assert ran["categoryOf"]["l-handed-off"] == "lost", (
        "a job that was handed off and then closed lost is filed as finished work")


@needs_node
def test_the_test_flag_still_beats_the_name_heuristic(ran):
    """`is_test: false` means somebody looked and said "real bid". A project genuinely called
    "Test Street Remodel" has to be able to leave the Test tab, which is why crm-core's isTest is
    a tri-state — read it, never re-implement it."""
    assert ran["categoryOf"]["a-testname-real"] == "active"
    assert ran["categoryOf"]["t-name"] == "test", "the name heuristic stopped working"


@needs_node
def test_nothing_the_board_calls_closed_lost_appears_under_active(ran):
    """Cross-checked against crm-core's own verdict on the same rows rather than against this
    page's fixture labels, so the two can't drift apart quietly."""
    for pid, stage in ran["boardStage"].items():
        if stage == "Closed lost":
            assert ran["categoryOf"][pid] == "lost", (
                "%s is Closed-lost on the CRM board and Active here" % pid)


# ── the pills ────────────────────────────────────────────────────────────────
@needs_node
def test_the_pill_counts_match_what_the_tab_renders(ran):
    """Rendered rows, counted out of the real HTML, against the pill on the same screen. A pill and
    a list that disagree is the bug worth catching here, and it stays catchable now that Active runs
    past one page: the first page of a long category renders exactly a full page, and every category
    that fits renders all of it. Both halves are the same statement, so both live in one assertion
    rather than in a branch that could quietly stop testing anything.

    The page size is read out of the page, never retyped, so raising PP_PER_PAGE cannot make this
    pass by accident."""
    for tab, seen in ran["tabs"].items():
        want = min(seen["pillCounts"][tab], ran["pageSize"])
        assert seen["rows"] == want, (
            "the %s pill says %d and the tab renders %d rows on page one, wanted %d"
            % (tab, seen["pillCounts"][tab], seen["rows"], want))
    assert ran["counts"]["active"] > ran["pageSize"], (
        "fixture drift: Active is meant to run past one page, which is what makes the min() above "
        "load-bearing rather than decorative")


@needs_node
def test_the_counts_are_the_same_whichever_tab_you_are_standing_on(ran):
    """They describe the whole list, not the current tab — a count that changed as you clicked
    around would be describing something else each time."""
    seen = [tuple(sorted(t["pillCounts"].items())) for t in ran["tabs"].values()]
    assert len(set(seen)) == 1
    assert dict(seen[0]) == ran["counts"], "the pills and ppCounts disagree"


@needs_node
def test_exactly_one_pill_reads_as_pressed(ran):
    for tab, seen in ran["tabs"].items():
        assert seen["pressed"] == [tab], (
            "%s: aria-pressed is on %r — a keyboard user is told the wrong tab is selected"
            % (tab, seen["pressed"]))


@needs_node
def test_clicking_the_count_badge_selects_the_tab_too(ran):
    """The badge is inside the button, so it is a perfectly ordinary click target. The handler is
    delegated and reads `e.target.closest("[data-pptab]")` for exactly this reason — reading
    `e.target.dataset.pptab` instead would work on the label and do nothing on the number, which
    reads as a dead spot in the middle of the pill."""
    assert ran["badgeClick"]["tab"] == "active"
    assert ran["badgeClick"]["pressed"] == ["active"]
    assert ran["badgeClick"]["rows"] == min(ran["counts"]["active"], ran["pageSize"])


@needs_node
def test_a_lost_test_project_says_so_and_only_there(ran):
    """Lost is the one tab where scratch work and real dead deals sit together, so the row has to
    carry it — the same call the board makes on its Lost cards. On the other three the tab IS the
    label, and a Test chip on every row of the Test tab would say nothing."""
    assert ran["tabs"]["lost"]["tagged"] == ["Demo Bid zz"], (
        "the Test tag is on the wrong Lost row, or on none of them")
    # Every OTHER tab, taken from the page's own list rather than spelled out here: a tab added
    # later must inherit this rule instead of quietly escaping it, which is how "won" sat in this
    # tuple naming nothing at all after the 2026-08-28 rename.
    for tab in [t for t in ran["tabIds"] if t != "lost"]:
        assert ran["tabs"][tab]["testTag"] == 0, "%s carries a Test tag" % tab


def test_the_test_tag_is_styled():
    css = PAGE_HTML.read_text(encoding="utf-8")
    assert ".pp-badge-test" in css, "the Test tag renders as an amber exception badge"


# ── pagination ───────────────────────────────────────────────────────────────
@needs_node
def test_a_full_page_holds_exactly_the_page_size(ran):
    """The size is read out of the page, never retyped here: changing PP_PER_PAGE must not need
    this file edited, and must not be able to pass while rendering a different number."""
    size = ran["pageSize"]
    assert ran["paging"]["p1"]["rows"] == size
    assert ran["paging"]["p2"]["rows"] == size


@needs_node
def test_the_pages_hold_consecutive_rows_with_no_gap_and_no_repeat(ran):
    """The off-by-one, killed by name. `rows.slice(page * N, ...)` reads perfectly well and skips
    the first page; `slice(start, N)` returns a shrinking window. Only the actual names prove it."""
    p = ran["paging"]
    seen = p["p1"]["names"] + p["p2"]["names"] + p["p3"]["names"]
    assert seen == ["Project %d" % i for i in range(1, 26)], (
        "the page slices do not tile the list in order")
    assert len(seen) == len(set(seen)), "a project appears on two pages"


@needs_node
def test_the_last_page_is_partial_and_the_page_count_is_right(ran):
    p = ran["paging"]
    assert p["p3"]["rows"] == 25 % ran["pageSize"] == 5
    for key in ("p1", "p2", "p3"):
        assert "Page %s of 3" % key[1] in p[key]["text"]
        assert "25 projects" in p[key]["text"], "the pager does not say how many there are"


@needs_node
def test_the_row_count_across_the_pages_equals_the_pill(ran):
    """The paged version of "the count matches the rows": with 25 in the category the pill cannot
    equal one page, so the sum is what has to agree.

    Mutation this kills: counting the SLICE instead of the pool, which would put 10 on the pill."""
    p = ran["paging"]
    assert (p["p1"]["rows"] + p["p2"]["rows"] + p["p3"]["rows"]
            == p["p1"]["pillCounts"]["active"] == 25)


@needs_node
def test_the_ends_of_the_range_disable_their_button(ran):
    p = ran["paging"]
    assert p["p1"]["prevDisabled"] and not p["p1"]["nextDisabled"]
    assert not p["p2"]["prevDisabled"] and not p["p2"]["nextDisabled"]
    assert not p["p3"]["prevDisabled"] and p["p3"]["nextDisabled"]


@needs_node
def test_prev_walks_back_through_the_same_pages(ran):
    """Not just Next: a pager that only counts up would leave you unable to get back to a row you
    just scrolled past."""
    assert ran["paging"]["backToP2"]["names"] == ran["paging"]["p2"]["names"]
    assert ran["paging"]["backToP2"]["page"] == 2


@needs_node
def test_a_page_past_the_end_clamps_instead_of_going_blank(ran):
    """A stored page from a longer list, or a project that just changed category under you, must
    not leave a list that renders nothing and looks broken."""
    # A disabled Next does not fire at all, which is the first line of defence.
    assert ran["paging"]["nextFiredPastEnd"] is False, (
        "Next is still clickable on the last page, so only the clamp stands between the reader "
        "and an empty list")
    assert ran["paging"]["past"]["page"] == 3 and ran["paging"]["past"]["rows"] == 5
    # And the clamp itself, reached the way a person reaches it: page 3 stored, then the list
    # shrinks to 12 under you.
    assert ran["clampedOnLoad"]["page"] == 2, "a stored page past the end was not clamped"
    assert ran["clampedOnLoad"]["rows"] == 2
    assert "Page 2 of 2" in ran["clampedOnLoad"]["text"]


@needs_node
def test_one_page_of_projects_shows_no_pager_at_all(ran):
    """"Page 1 of 1" beside two dead buttons is noise on the common case. EXACTLY one full page is
    the boundary worth pinning — `>` vs `>=` on the page count lands here."""
    assert ran["exactlyOnePage"]["rows"] == ran["pageSize"]
    assert ran["exactlyOnePage"]["hidden"] is True
    assert ran["elevenRows"]["hidden"] is False, "11 projects at 10 a page needs a pager"
    assert ran["elevenRows"]["rows"] == 1
    assert "Page 2 of 2" in ran["elevenRows"]["text"]


@needs_node
def test_changing_tab_goes_back_to_page_one(ran):
    """Page 3 of Active means nothing in Handed Off, and landing on an out-of-range page in a new
    category is how you get a blank list on the first click."""
    p = ran["paging"]
    assert p["beforeTabSwitch"]["page"] == 3, "fixture drift: the switch is meant to happen deep in"
    assert p["afterTabSwitch"]["page"] == 1
    assert p["backToActive"]["page"] == 1
    assert p["backToActive"]["names"][0] == "Project 1", (
        "coming back to a tab resumed the old page instead of starting at the first")


@needs_node
def test_the_reset_is_the_handler_and_not_the_clamp_catching_it(ran):
    """The case above cannot actually see the bug and I only found that out by mutating: from page 3
    of Active to an EMPTY Handed Off lands on page 1 either way, because the clamp shortens it.
    Dropping the handler's own `ppGoto(1)` passed the whole suite.

    With 25 rows on BOTH sides there is nothing to clamp, so a kept page number shows up as page 3
    of the tab you just opened — 15 rows down a list you have not looked at yet."""
    d = ran["deepSwitch"]
    assert d["from"]["page"] == 3 and d["from"]["tab"] == "active", "fixture drift"
    assert d["to"]["page"] == 1, (
        "switching to a tab that is long enough kept the page you were on — the reset is coming "
        "from the clamp, not from the tab handler")
    assert d["to"]["names"][0] == "Scratch 1"
    assert d["back"]["page"] == 1 and d["back"]["names"][0] == "Project 1"


# ── the empty states ─────────────────────────────────────────────────────────
@needs_node
def test_an_empty_category_says_so_rather_than_rendering_an_empty_list(ran):
    """Three different kinds of empty, three different answers — only one of them means "clear
    the filter"."""
    assert "No Handed Off projects yet." in ran["paging"]["afterTabSwitch"]["html"]
    assert ran["paging"]["afterTabSwitch"]["rows"] == 0
    assert "No published proposals yet." in ran["emptyNothingLoaded"]["html"], (
        "nothing loaded at all reads as an empty category")
    assert "No Test projects match your search." in ran["emptyFiltered"]["html"], (
        "a category hidden by the search reads as genuinely empty, so nobody clears the filter")


@needs_node
def test_an_empty_category_hides_the_pager(ran):
    assert ran["paging"]["afterTabSwitch"]["hidden"] is True


@needs_node
def test_typing_in_the_search_goes_back_to_page_one(ran):
    """Page 3 of the old pool is meaningless once the pool narrows, and the clamp alone would
    leave you on the LAST page of the results rather than the first — which reads as a search
    that found nothing until you notice the pager."""
    assert ran["searchResetsPage"]["page"] == 1
    assert ran["searchResetsPage"]["names"][0] == "Project 1"
    assert ran["searchResetsPage"]["rows"] == ran["pageSize"], (
        "fixture drift: this search is meant to leave more than one page")


@needs_node
def test_the_counts_follow_the_search(ran):
    """The search box sits directly above the pills: a pill reading 40 that then shows 2 rows is
    describing a list nobody can see.

    Mutation this kills: `syncPpTabs(ppCounts(PROJECTS))` — the pills keep their full numbers and
    every one of them lies while a filter is typed."""
    assert ran["search"]["pillCounts"] == {"active": 1, "handed_off": 0, "lost": 0, "test": 1}, (
        "the pills are counting the unfiltered list")
    assert ran["search"]["rows"] == 1
    assert set(ran["emptyFiltered"]["pillCounts"].values()) == {0}, (
        "a search matching nothing still leaves numbers on the pills")


# ── the choice survives ──────────────────────────────────────────────────────
@needs_node
def test_the_chosen_tab_and_page_survive_a_reload(ran):
    """A second scope over the same sessionStorage, which is what a reload is. Within the page's
    own re-renders the module vars already carry it; this is the half that would quietly stop
    working if either ssSet call went missing."""
    assert ran["reload"]["tab"] == "active" and ran["reload"]["page"] == 3
    assert ran["reload"]["names"] == ["Project %d" % i for i in range(21, 26)], (
        "the stored page was restored as a number but the list did not follow it")
    assert ran["reloadTab"]["tab"] == "lost" and ran["reloadTab"]["page"] == 1


@needs_node
def test_a_junk_stored_tab_falls_back_to_the_working_list(ran):
    """Checked against the known set, not trusted from storage or the attribute: an unrecognised
    tab that filtered everything out would blank the card with no way to recover but a reload."""
    assert ran["junkStoredTab"]["tab"] == "active"
    assert ran["junkStoredTab"]["rows"] == min(ran["counts"]["active"], ran["pageSize"]), (
        "the fallback landed on Active but rendered somebody else's list")


# ── the chips, which are the point of the page ────────────────────────────────
@needs_node
def test_a_chip_on_page_two_still_writes_the_right_override(ran):
    """The rows are re-generated on every render, so the handlers are attached to fresh HTML.
    "Does a toggle on page 2 send the PUT for the project on page 2" is behaviour — and the pid is
    the thing a bad slice gets wrong without changing anything visible."""
    assert ran["chipsOnPage2"]["pid"] == "p11", "page 2 is not the second slice of the list"
    assert ran["mutePut"]["path"] == "/api/portal/proposal/p11/notify-overrides"
    assert ran["mutePut"]["method"] == "PUT"
    assert ran["mutePut"]["body"] == {"email": "hanz@wetreadwell.com", "mode": "mute"}


@needs_node
def test_toggling_back_to_the_global_default_clears_rather_than_re_adds(ran):
    """`mode: clear` when the new state equals the global base — an override that merely restates
    the default is a per-project exception nobody asked for, and it shows up as "1 custom"."""
    assert ran["clearPut"]["body"] == {"email": "hanz@wetreadwell.com", "mode": "clear"}
    assert ran["afterClear"]["overrides"] == {}


@needs_node
def test_a_toggle_keeps_you_on_the_tab_and_page_you_were_on(ran):
    """The re-render after a PUT is the obvious place to lose your place. Reaching for the same
    person on page 3 of Lost after every click is the bug this pins."""
    assert ran["afterMute"] == {"page": 2, "tab": "active",
                                "overrides": {"p11": {"hanz@wetreadwell.com": "mute"}},
                                "eff": "0", "rows": 10}
    assert ran["afterClear"]["page"] == 2
    assert ran["afterAdd"]["tab"] == "lost" and ran["afterAdd"]["page"] == 1


@needs_node
def test_a_chip_works_on_a_non_active_tab_too(ran):
    """Kyle is off in the global roster, so the same click has to produce `add` rather than
    `mute` — the mode is derived from the base state, not from the direction of travel."""
    assert ran["addPut"]["path"] == "/api/portal/proposal/l-price/notify-overrides"
    assert ran["addPut"]["body"] == {"email": "kyle.loseke@wetreadwell.com", "mode": "add"}
    assert ran["afterAdd"]["overrides"] == {"l-price": {"kyle.loseke@wetreadwell.com": "add"}}


@needs_node
def test_a_non_admin_can_still_only_toggle_themselves(ran):
    """Server-enforced either way, but a chip that looks pressable and 403s is worse than a
    disabled one. Unchanged behaviour — asserted because the row markup moved into ppRowHtml."""
    by = {c["email"]: c["disabled"] for c in ran["nonAdminChips"]}
    assert by["kyle.loseke@wetreadwell.com"] is False, "a non-admin cannot toggle their own chip"
    assert by["hanz@wetreadwell.com"] is True, "a non-admin can toggle somebody else"


@needs_node
def test_every_rendered_row_carries_the_whole_roster(ran):
    """Two people on the roster, so a row is two chips. Catches a slice applied to the PEOPLE
    rather than to the projects."""
    for tab, seen in ran["tabs"].items():
        assert seen["chipCount"] == seen["rows"] * 2, (
            "%s renders %d rows and %d chips" % (tab, seen["rows"], seen["chipCount"]))


# ── the things a source read is the right tool for ───────────────────────────
def test_the_categories_come_from_crm_core_and_are_not_re_implemented():
    """The one rule this page must not break. `is_test` is a tri-state and `stage()` has an order;
    a second copy of either is how the CRM board and this page start disagreeing about the same
    project. projects.js already carries a duplicate of the test heuristic and needs a test
    comparing the two character for character to keep it honest — don't add a third."""
    js = PAGE_JS.read_text(encoding="utf-8")
    assert "C.isLost(" in js and "C.isTest(" in js, (
        "the categories no longer read crm-core's predicates")
    # Won moved into crm-core on 2026-08-19 — "CRM lost and won should also tie up to the
    # notification sending okay?". It was defined here, in the only page that then had a Won tab,
    # which is precisely how two screens end up disagreeing about a word Troy reads as a number.
    # Since 2026-08-28 this page routes on isHandedOff instead, and the same rule applies to it: the
    # whole predicate comes from crm-core, never the ingredients.
    #
    # `C.isHandedOff(` with the paren, deliberately. The page binds it once as
    # `const isHandedOff = C.isHandedOff;` and calls the local name, so a bare substring would also
    # be satisfied by a COMMENT mentioning it — which is exactly the false pass the old
    # `assert "isWon" in js` degraded into the moment the page stopped calling isWon.
    assert "C.isHandedOff" in js, "the hand-off state is no longer read from crm-core"
    assert "C.depositSatisfied(" not in js, (
        "the page is assembling its categories out of crm-core's ingredients instead of asking it")
    for own in ("function isLost", "function isTest", "function nameLooksLikeTest",
                "function isWon", "function isHandedOff", "function depositSatisfied",
                "closed_lost", "approved_at", "handed_off_at"):
        assert own not in js, (
            "notifications.js has its own %r — it must read crm-core, which is the one place "
            "that decides what a project is" % own)


def test_the_pager_is_real_buttons_so_the_keyboard_reaches_it():
    """Tab reaches a <button> and Enter/Space fire its click with no key handling at all. A
    div-with-a-listener needs tabindex, a role, and two key handlers to get to the same place."""
    js = PAGE_JS.read_text(encoding="utf-8")
    for ctl in ('id="pp-prev"', 'id="pp-next"'):
        line = next(l for l in js.splitlines() if ctl in l)
        assert "<button" in line and 'type="button"' in line, (
            "%s is not a real button, so the keyboard cannot reach it" % ctl)
    assert 'id="pp-pgn" aria-live="polite"' in js, (
        "the page indicator is not announced, so a keyboard user gets no feedback from Next")


def test_every_id_the_page_looks_up_is_one_it_actually_renders():
    """The gap the harness cannot see: it supplies the ids by hand, so a typo in render() would
    still resolve there. In the browser `$("pp-prev")` returns null, every sync guards with
    `if (prev)`, and the pager is silently inert — a control that renders and does nothing.

    Both lists come out of the file, so a renamed node has to be renamed in both places."""
    js = PAGE_JS.read_text(encoding="utf-8")
    written = set(re.findall(r'id="((?:pp|nn)-[a-z]+)"', js))
    looked_up = set(re.findall(r'\$\("((?:pp|nn)-[a-z]+)"\)', js))
    assert written, "render() writes no ids at all — this test is reading the wrong thing"
    missing = looked_up - written
    assert not missing, (
        "these are looked up but never rendered, so they resolve to null and their control does "
        "nothing at all: %s" % sorted(missing))


def test_the_tabs_are_real_buttons_with_a_count_badge():
    js = PAGE_JS.read_text(encoding="utf-8")
    assert 'class="tw-tab" data-pptab=' in js
    assert '<span class="n">0</span>' in js, "the pill has no count badge to fill"
    css = PAGE_HTML.read_text(encoding="utf-8")
    assert ".tw-tab" in css and '.tw-tab[aria-pressed="true"]' in css, (
        "the pills are unstyled, or the selected one is marked by nothing")
    # The page-boot suite forbids !important here and forbids re-defining .tw-av; the new rules
    # must not have reached for either.
    assert "!important" not in css
