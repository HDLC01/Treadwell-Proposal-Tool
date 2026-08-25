"""Active Projects is the main tab: it sits first, it can start a bid, and every card opens files.

Hanz, 2026-08-12, looking at production:

    "Move the Proposal database down and create its own cateogry"
    "This active Projects tab will be the Main tab for all. Majority of the Sales Meeting will
     be held in this tab"
    "Since we moved the proposals database down below. We need to ccreate a way so that when we
     click a container we are able to create a proposal under that not sent category. That would
     in turn lead us to our current intake form, estimate excel sheet etc. There should be a
     button for each. container for the files and info sheet as well."

WHY THE ORDER MATTERS RATHER THAN BEING COSMETIC. Proposals Database was directly above Active
Projects, which read as "start here". That was true while the Database was the only place to mint
a draft. It stopped being true the moment this board grew a + New button, and a page you run the
weekly sales meeting from should not be something you scroll past to reach.

THE ROUTES ARE NOT RE-SPELLED. The Files and Info buttons use exactly the URLs projects.js
already uses. Two spellings of one route is how one of them rots — and this file compares them
character for character, in both directions, so a change to either page has to move both.

WHY A + New BUTTON IS SAFE HERE AT ALL. It reuses the Database's mechanism verbatim (clear three
storage keys, set the test intent, navigate to /?new=1). The test intent follows the TAB you are
looking at, and this board is always on Active or Test — never an "all" view — so a project
started here can never land un-filed. That was Hanz's rule on 2026-08-10: "when we test something
please dont use the production Active tab for projects. Use the 'Test' category so it wouldnt mix
up."
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


def _src(name: str) -> str:
    return (FRONTEND / "js" / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """Source with // comment lines stripped. This file's own prose quotes what it asserts, and
    so do the files it reads — the fourth time that bit in one week."""
    return "\n".join(l for l in _src(name).splitlines() if not l.strip().startswith("//"))


def _braced(src: str, i: int, what: str) -> str:
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
    src = _code(name)
    m = re.search(r"\n\s{2,6}(?:async\s+)?function " + re.escape(fn) + r"\s*\(", src)
    assert m, "%s() is gone from %s: rewrite these tests, don't delete them" % (fn, name)
    return _braced(src, m.end(), "%s() in %s" % (fn, name))


def _sidebar() -> str:
    """The sidebar markup expression from auth.js, comments stripped."""
    code = _code("../auth.js") if (FRONTEND / "js" / "../auth.js").exists() else None
    src = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    src = "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))
    i = src.index("aside.innerHTML")
    return src[i:src.index("</nav>", i)]


# ── the order ────────────────────────────────────────────────────────────────
def test_active_projects_is_the_first_item_in_the_sidebar():
    """"the Main tab for all". Not the second item under a heading about something else."""
    bar = _sidebar()
    first = re.search(r'navItem\("(/[a-z-]+\.html)"', bar)
    assert first and first.group(1) == "/portal.html", (
        "the first sidebar item is %s, not Active Projects" % (first and first.group(1)))


def test_the_proposals_database_moved_BELOW_active_projects():
    bar = _sidebar()
    assert bar.index('"/portal.html"') < bar.index('"/projects.html"'), (
        "Proposals Database is still above Active Projects")


def test_the_proposals_database_is_not_where_a_bid_starts():
    """"create its own cateogry" (Hanz, 2026-08-12). It was a tail item under Proposals sitting
    directly above Active Projects, which read as the place to start a bid. It is the opposite of
    that: every proposal ever drafted, most of them never sent — a filing cabinet you go to on
    purpose.

    IT HAD A "Database" HEADING FROM THAT DAY UNTIL 2026-08-25, when the sidebar collapsed to three
    headings and it joined the other look-back pages under Active. The heading is gone; the
    decision behind it is not, and what carries it now is POSITION — the Database sits below every
    page the day actually runs on, never above them. Asserted against all five of those rather than
    against Active Projects alone, because "below the board" was already true of the arrangement he
    complained about."""
    bar = _sidebar()
    i = bar.index('"/projects.html"')
    for href in ('"/portal.html"', '"/followups.html"', '"/leads.html"', '"/crm.html"',
                 '"/calendar.html"'):
        assert bar.index(href) < i, (
            "%s is below the Proposals Database, so the filing cabinet is back among the daily "
            "pages" % href)
    heading = None
    for m in re.finditer(r'tw-section">([^<]+)</div>', bar):
        if m.start() < i:
            heading = m.group(1)
    assert heading == "Active", (
        "Proposals Database sits under %r rather than Active" % heading)


def test_nothing_else_left_the_sidebar():
    """Reordering is easy to do destructively. Every page that is meant to be linked stays linked.

    The polish beta is listed by its INTAKE, which is its own step 1. That door moved there on
    2026-08-17, when the five job conditions moved off the calculator onto the beta intake form:
    opening at step 2 would start an estimator pricing before the switches that change the price
    have been seen. The calculator is still reachable — from the beta's own step nav and from the
    toolbar link on Estimate Review — so what this list guards is the DOOR, not every page.

    FOLLOW-UPS JOINED THIS LIST ON 2026-08-24, under Sales, one row below Active Projects. It had
    been unlinked since 2026-08-10 and Hanz reversed that: "make sure all follow up emails are shown
    in the Chat box and in the Follow Ups section." It is asserted here as well as in
    test_sidebar_labels.py because this is the file somebody edits when they reorder the menu, and a
    second Sales row is the easiest thing in the list to lose to a tidy-up. Its permission entry is
    pinned below, beside the Info Sheet's, for the same reason.

    INFO SHEET CAME OFF THIS LIST ON 2026-08-20, and the removal is the one thing here that was
    intended. Hanz moved it into the project drawer's Proposal tab: the sidebar row had no project
    in hand, so it could only ever open a choose-a-project state, while from the drawer the hand-off
    is one click on the job on screen. The assertion is INVERTED rather than deleted, because a
    sidebar row reappearing is how you end up with two doors to one page and only one of them
    carrying the ?d= — auth.js's draft-id rewrite went out with the row.

    Removed from the MENU is not removed from the POLICY: nav_access.py keeps the tab's capability
    entry and names it in NO_SIDEBAR_TABS, so /api/info-sheet/* is still refused per role. The test
    below pins that, because deleting the entry is the cheap way to keep a list like this green."""
    bar = _sidebar()
    for href in ("/portal.html", "/followups.html", "/projects.html", "/leads.html", "/crm.html",
                 "/calendar.html", "/polish-intake.html", "/analytics.html", "/library.html",
                 "/history.html", "/trash.html", "/notifications.html",
                 "/followup-settings.html", "/admin.html"):
        assert '"%s"' % href in bar, "%s is no longer reachable from the sidebar" % href
    assert "/info-sheet.html" not in bar, (
        "Info Sheet is back in the sidebar. It moved into the project drawer's Proposal tab on "
        "2026-08-20; the menu row opens a page with no project in hand, and the ?d= rewrite that "
        "used to patch it came out of auth.js with the row.")


def test_the_info_sheet_kept_its_permission_when_it_left_the_menu():
    """The half of that move that is easy to lose. A tab with no sidebar row is still a tab: the
    entry in nav_access.TABS is what refuses /api/info-sheet/* to a denied role and what makes the
    page paint a refusal instead of itself.

    Asserted here as well as in test_nav_access.py because THIS file is the one somebody edits when
    they take a row out of the sidebar, and deleting the capability entry is the change that makes
    the rest of the suite go quiet while silently removing a gate."""
    import nav_access
    assert "/info-sheet.html" in nav_access.TABS, (
        "the Info Sheet tab lost its capability entry, so its page and /api/info-sheet/* are no "
        "longer deniable to anybody — that is a removed permission, not a sidebar cleanup")
    assert "/info-sheet.html" in nav_access.NO_SIDEBAR_TABS, (
        "the tab has no sidebar row and is not declared hidden, so nothing says the missing row "
        "was on purpose")
    assert nav_access.TABS["/info-sheet.html"]["api"] == ("/api/info-sheet/",)


def test_the_follow_ups_board_GAINED_a_permission_when_it_came_back_to_the_menu():
    """The exact mirror of the test above, and the half of the 2026-08-24 relink that is easy to
    miss: a row in the menu with no entry in nav_access.TABS is a tab the Admin page cannot draw a
    switch for and the middleware cannot refuse. It was ungoverned for a fortnight because it was
    also unlinked, which was consistent; a linked row that is still ungoverned is not.

    /api/portal/followups is the feed and followups.js is its only caller, so the tab may own it.
    The routes its buttons post to are the CRM drawer's as well and are deliberately absent
    (test_nav_access.py::test_no_tab_claims_a_shared_prefix is the general form)."""
    import nav_access
    assert "/followups.html" in nav_access.TABS, (
        "the Follow-ups board is in the sidebar with no capability entry, so no role can be denied "
        "it and /api/portal/followups is ungated")
    assert nav_access.TABS["/followups.html"]["api"] == ("/api/portal/followups",)
    assert "/followups.html" not in nav_access.NO_SIDEBAR_TABS, (
        "the board is drawn in the menu, so it is not one of the rowless tabs")
    assert "/followups.html" not in nav_access.ALWAYS_OPEN_PAGES, (
        "the page is in TABS and in ALWAYS_OPEN_PAGES at once: governed and ungovernable")


def test_the_active_highlight_still_comes_from_the_path():
    """Why moving items is safe at all: navItem compares location.pathname, never the label or
    the position. If that ever changed to an index, every move here would break a highlight."""
    src = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    body = src[src.index("function navItem"):]
    body = body[:body.index("\n  }") + 4]
    assert "location.pathname" in body and "endsWith" in body


# ── starting a bid from the board ────────────────────────────────────────────
def test_only_the_created_but_not_sent_column_offers_a_new_proposal():
    """Every other column's membership rule needs the customer to have been sent something, so a
    brand-new project could not satisfy it — the button would lie about where the card lands."""
    body = _block("portal.js", "kanbanHtml")
    assert "data-new-proposal" in body, "the + New button is gone"
    # The WHOLE gate expression, not just the presence of the condition. `true || s ===
    # STAGE_CREATED` keeps the string and puts a + New on all seven columns — a mutation did
    # exactly that and survived the looser regex.
    m = re.search(r"const add = (.+?);\n", body, re.S)
    assert m, "the + New button is no longer one guarded expression"
    gate = m.group(1)
    assert "s === STAGE_CREATED" in gate, (
        "the + New button is not gated on the Created-but-not-sent column")
    rest = gate.replace("s === STAGE_CREATED", "")
    for always in ("true", "||", "1 ?"):
        assert always not in rest, (
            "the gate short-circuits to always-on, so every column offers + New: %r" % gate.strip())


def test_the_button_is_inside_the_column_header_the_board_repaints():
    """renderBoard replaces #board's innerHTML every 25s. A button appended from outside the
    template would vanish on the first poll."""
    body = _block("portal.js", "kanbanHtml")
    i = body.index("data-new-proposal")
    j = body.index("return `<div class=\"col")
    assert i < body.index("${add}", j), "the button is not interpolated into the header template"


def test_starting_a_bid_reuses_the_database_mechanism_exactly():
    """A second way to mint a draft is a second set of bugs. Compared against projects.js rather
    than against a list written here, so the two cannot drift."""
    mine = _block("portal.js", "startNewProposal")
    theirs = _code("projects.js")
    for key in ("treadwell.proposal_tool.state", "treadwell.proposal_tool.draft_id",
                "treadwell.proposal_tool.hydrated_once"):
        assert key in mine, "the board does not clear %s, so the new form resumes an old draft" % key
        assert key in theirs, "projects.js no longer clears %s; this comparison has moved" % key
    assert '"/?new=1"' in mine and '"/?new=1"' in theirs, (
        "the two entry points disagree about where the intake form is")


def test_a_project_started_from_the_board_is_filed_by_the_tab_you_are_on():
    """Hanz, 2026-08-10: test work must not mix into Active. The board is always on one tab or
    the other, so this can pass a definite true/false and never a null."""
    mine = _block("portal.js", "startNewProposal")
    assert re.search(r'setNewProjectTestIntent\(TAB === "test"\)', mine), (
        "the new project does not follow the tab, so scratch work can land in Active")


def test_losing_local_storage_does_not_stop_you_starting_a_bid():
    """Private mode throws on removeItem. The intake form is reachable by URL regardless, so the
    navigation must not be inside the try."""
    mine = _block("portal.js", "startNewProposal")
    i, j = mine.index("try {"), mine.index("location.assign")
    catch = mine.index("catch", i)
    assert catch < j, "the navigation is inside the try block and a storage failure would skip it"


# ── the outcome, on every undecided card ─────────────────────────────────────
def test_every_undecided_card_gets_the_two_outcome_buttons():
    """The card's two buttons are [Mark as won] and [Lost].

    WHO AND WHEN: Hanz, 2026-08-20 — "Instead of Files and Info Sheet, we chane it to mark as
    closed and Lost button". This test was `test_every_card_gets_files_and_info` and pinned the
    2026-08-12 pair, which is the decision this one reverses: Files and Info sheet moved into BOTH
    drawers' Proposal tab the same day (#go-files/#go-info on the sent side, [data-go-files]/
    [data-go-info] on the not-sent side), so nothing is out of reach and the card gets the room
    back for the thing the sales meeting actually needs from it.

    "Closed" MEANS WON, which is why there is no third state anywhere: the button posts the won
    mark that already exists. Whether it does is a question for test_card_actions.py, which runs
    the handler; this file is about the board's structure, so it asks whether the row is rendered
    on the cards at all and on which of them.

    Still not gated on `not_sent` — both endpoints exist for both kinds of card — but gated on
    whether the job is already decided, because a Lost button on a lost card saves and changes
    nothing visible."""
    kanban = _block("portal.js", "kanbanHtml")
    assert "cardActions(p)" in kanban, "the action row is not rendered on cards"
    acts = _block("portal.js", "cardActions")
    assert "data-won=" in acts and "data-lost=" in acts, (
        "the card does not carry Mark as won and Lost")
    assert "data-files=" not in acts and "data-info=" not in acts, (
        "the old Files/Info sheet pair is back on the card as well")
    assert "not_sent" not in acts, "the buttons are gated on the not-sent rows only"
    assert "isLost(p)" in acts and "isWon(p)" in acts, (
        "an already-decided card is offered a button that cannot change anything")


def test_the_urls_match_the_proposals_database_character_for_character():
    """Two spellings of one route is how one of them rots. Asserted in BOTH directions, so
    renaming a route on either page fails here until both move.

    The two links moved off the card and into the drawers' Proposal tab on 2026-08-20, so this
    reads the whole of portal.js rather than cardActions. Which element carries them is a
    different question; that they are spelled the way projects.js spells them is this one."""
    board_click = _code("portal.js")
    theirs = _code("projects.js")
    assert '/done.html?d=' in board_click and '"&files=1"' in board_click
    assert '"/done.html?d=" + id + "&files=1"' in theirs, (
        "projects.js changed its files URL; the board must move with it")
    assert '"/info-sheet.html?d=" + id' in theirs, (
        "projects.js changed its info-sheet URL; the board must move with it")
    assert "/info-sheet.html?d=" in board_click


def test_the_id_is_encoded_before_it_reaches_a_url():
    acts = _block("portal.js", "cardActions")
    assert "encodeURIComponent(p.proposal_id)" in acts


def test_clicking_a_button_does_not_also_open_the_drawer():
    """Both buttons live inside .deal, which is the drawer's own click target. Without an early
    return the click acts AND opens the drawer, and the drawer wins the repaint — so the button
    looks broken.

    The pair being guarded changed on 2026-08-20 (Hanz: "Instead of Files and Info Sheet, we chane
    it to mark as closed and Lost button"), and the property did not: whatever the card's controls
    are, each branch has to come before the row branch and has to return. The old pair navigated;
    these two post and repaint, which is strictly worse to lose, because the drawer's repaint would
    hide the button's own failure message.

    STILL A SOURCE READ, and deliberately not the only test of this: test_card_actions.py drives
    the real listener with a real click for all six paths and asserts the drawer stayed shut. This
    one reads the branch ORDER, which a passing behavioural test cannot distinguish from luck."""
    code = _code("portal.js")
    i = code.index('$("board").addEventListener("click"')
    handler = _braced(code, i, "the board click handler")
    won_at = handler.index("[data-won]")
    lost_at = handler.index("[data-lost]")
    new_at = handler.index("[data-new-proposal]")
    row_at = handler.index('closest(".deal, .trow")')
    assert won_at < row_at and lost_at < row_at and new_at < row_at, (
        "a button branch runs after the row branch, so the drawer opens over the action")
    # Each branch scoped to its OWN statement — up to the NEXT branch, not up to the row handler.
    # Spanning further let one branch with no `return` be satisfied by the next branch's, and that
    # mutation survived: the click would act AND open the drawer, drawer winning.
    bounds = sorted([won_at, lost_at, new_at, row_at])
    for needle, start in (("[data-won]", won_at), ("[data-lost]", lost_at),
                          ("[data-new-proposal]", new_at)):
        end = next(b for b in bounds if b > start)
        assert "return" in handler[start:end], (
            "the %s branch does not return, so the drawer opens over the action" % needle)


def test_the_buttons_are_styled_and_the_column_header_can_hold_one():
    """A header that was `display:flex; justify-content:space-between` with two children puts a
    third in the middle. The count keeps the middle; the button is pushed to the end."""
    page = (FRONTEND / "portal.html").read_text(encoding="utf-8")
    assert ".col-add" in page and ".deal-act" in page, "the new controls have no styling"
    m = re.search(r"\.col h2 \{[^}]*\}", page)
    assert m and "align-items:center" in m.group(0), (
        "the column header does not centre a button against the title")
    assert re.search(r"\.col h2 \.col-add \{[^}]*margin-left:auto", page), (
        "the + New button is not pushed past the count")
