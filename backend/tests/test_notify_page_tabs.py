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
  * TEST beats WON, because a test project's outcome is fiction. Won is a number a human reads as
    real work, and somebody's scratch bid must not be able to inflate it. The board agrees: it has
    no Won tab, and a won test project sits on its Test tab.
  * ACTIVE is the REMAINDER, never a predicate of its own. That is what makes the four a partition
    and what stops a project the categories don't recognise from being reachable from no tab.

WON IS APPROVED **AND** THE DEPOSIT SETTLED, and both halves are load-bearing.

`depositSatisfied` alone is far too generous — it is true of any job that collects no deposit,
including a proposal emailed this morning that nobody has opened (`a-nodeposit-unapproved` below).
Approval alone is too generous the other way: an approved job whose deposit is still outstanding
is the single most worth-chasing project there is, and filing it under Won hides it from the person
whose job is to chase it. So it stays under Active, which is also where the CRM board keeps it —
its Approved and Deposit-submitted columns are both live.

followups.js reached the same line from the other side and its tab is LABELLED "Approved" rather
than Won, because approval alone does not earn the word. This page has the deposit signal in the
same row, so it can afford the stricter test and keep the honest label.

THE ONE PLACE THIS PAGE AND THE CRM BOARD DIFFER, stated rather than hidden: a won project is still
on the board's ACTIVE board (in its "Deposit received" or "Contact info" column) while this page
files it under Won. That is the whole point of the ask — those rows were the clutter — and no row
changes category, only which of this page's tabs shows it. Nothing the board calls Closed lost can
appear under Active here, and nothing it calls Test can either.

EVERYTHING BELOW IS EXECUTED. The house rule, bought the hard way on 2026-08-12: a source-text
assertion cannot see an unbound identifier, and that class of bug took the board down on prod with
every test green. `js/notify-tabs-harness.js` lifts the real functions out of notifications.js,
runs them against the real crm-core.js and a DOM stub, and reports what actually rendered.
"""
import json
import pathlib
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
                             "a-testname-real"}
    assert got["won"] == {"w-deposit-in", "w-no-deposit-needed", "w-contacts-in"}
    assert got["lost"] == {"l-price", "l-test", "l-was-won"}
    assert got["test"] == {"t-flag", "t-name", "t-won"}


@needs_node
def test_every_project_lands_in_exactly_one_category_and_none_is_dropped(ran):
    """The property the pills depend on, and the assertion that matters most here: a project
    silently vanishing off this page means somebody's notification recipients become unreachable
    and nobody finds out.

    Mutations this kills: making Active a predicate of its own (`!isLost && !isTest && !isWon`
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
def test_a_won_test_project_is_test_not_won(ran):
    """A scratch bid's outcome is fiction. Won is read as real work, so a test project must not be
    able to inflate it — and the board files this same row under Test."""
    assert ran["depositSatisfied"]["t-won"] is True, (
        "fixture drift: this row is supposed to be one Won would otherwise claim")
    assert ran["categoryOf"]["t-won"] == "test", (
        "a test project is being counted as Won, so the Won pill overstates real work")


@needs_node
def test_a_project_lost_after_it_was_approved_and_paid_is_still_lost(ran):
    """Money came in and the job died anyway. Lost is above Won for the same reason it is above
    Test: the board says Closed lost, and this page must not say otherwise."""
    assert ran["categoryOf"]["l-was-won"] == "lost"
    assert ran["depositSatisfied"]["l-was-won"] is True, (
        "fixture drift: this row is supposed to be one Won would otherwise claim")


@needs_node
def test_approved_with_the_deposit_still_outstanding_stays_active(ran):
    """The judgement call, pinned. These two are the most worth-chasing rows on the page, and Won
    would hide them from the person whose job is the chasing. The board keeps them live too."""
    for pid in ("a-approved-owes", "a-approved-submitted"):
        assert ran["categoryOf"][pid] == "active", (
            "%s is filed as Won while its deposit is outstanding" % pid)
        assert ran["depositSatisfied"][pid] is False


@needs_node
def test_deposit_satisfied_alone_does_not_make_a_project_won(ran):
    """`a-nodeposit-unapproved` is a no-deposit job emailed this morning that nobody has opened.
    depositSatisfied says True about it, because that predicate answers "is money outstanding",
    not "did we win".

    Mutation this kills: `isWon = C.depositSatisfied`, which is the tempting one-liner."""
    assert ran["depositSatisfied"]["a-nodeposit-unapproved"] is True
    assert ran["categoryOf"]["a-nodeposit-unapproved"] == "active", (
        "an unopened proposal is being counted as Won because it collects no deposit")


@needs_node
def test_won_covers_both_ways_the_deposit_question_can_be_settled(ran):
    """Received, and legitimately-none — a GC job that collects no deposit is won on approval, and
    would otherwise sit in Active forever with nothing left to do to it."""
    assert ran["categoryOf"]["w-deposit-in"] == "won"
    assert ran["categoryOf"]["w-no-deposit-needed"] == "won"


@needs_node
def test_a_project_the_portal_moved_past_approval_is_still_won(ran):
    """`proposal_status` is no longer "approved" once contacts land, which is exactly why
    crm-core's stage() reads deposit state before it. isWon reads `approved_at` as well, and that
    stamp never unsets.

    Mutation this kills: dropping the `|| !!p.approved_at`, which quietly moves every finished job
    back into the working list the moment the customer submits contacts."""
    assert ran["categoryOf"]["w-contacts-in"] == "won"
    assert ran["boardStage"]["w-contacts-in"] == "Contact info", "fixture drift"


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
    """Rendered rows, counted out of the real HTML. Every category here fits one page, so the
    pill and the row count are directly comparable; the paged case is checked below."""
    for tab, seen in ran["tabs"].items():
        assert seen["pillCounts"][tab] == seen["rows"], (
            "the %s pill says %d and the tab renders %d rows"
            % (tab, seen["pillCounts"][tab], seen["rows"]))


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
    assert ran["badgeClick"]["rows"] == 7


@needs_node
def test_a_lost_test_project_says_so_and_only_there(ran):
    """Lost is the one tab where scratch work and real dead deals sit together, so the row has to
    carry it — the same call the board makes on its Lost cards. On the other three the tab IS the
    label, and a Test chip on every row of the Test tab would say nothing."""
    assert ran["tabs"]["lost"]["tagged"] == ["Demo Bid zz"], (
        "the Test tag is on the wrong Lost row, or on none of them")
    for tab in ("active", "won", "test"):
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
    """Page 3 of Active means nothing in Won, and landing on an out-of-range page in a new
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
    of Active to an EMPTY Won lands on page 1 either way, because the clamp shortens it. Dropping
    the handler's own `ppGoto(1)` passed the whole suite.

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
    assert "No Won projects yet." in ran["paging"]["afterTabSwitch"]["html"]
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
    assert ran["search"]["pillCounts"] == {"active": 1, "won": 0, "lost": 0, "test": 1}, (
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
    assert ran["junkStoredTab"]["rows"] == 7


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
    assert "C.isLost(" in js and "C.isTest(" in js and "C.depositSatisfied(" in js, (
        "the categories no longer read crm-core's predicates")
    for own in ("function isLost", "function isTest", "function nameLooksLikeTest",
                "function depositSatisfied", "closed_lost"):
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
