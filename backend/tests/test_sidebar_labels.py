"""The sidebar's Proposals section, renamed and de-cluttered (Hanz, 2026-08-10).

WHAT HE ASKED FOR, IN HIS WORDS.

    Change "Projects" sidebar label to Proposals Database
    and Customer Portal CRM TO "Active Projects"
    ...
    Remove the followups on the sidebar.

WHY THE RENAME. Two of the eleven sidebar items were named after the code rather than the job.
"Projects" is every proposal anybody has ever drafted, most of them never sent to a customer, so
it is a record you search. "Customer Portal CRM" is the short list of jobs that are live with a
customer right now, which is the one Troy opens every morning. Standing in the sidebar neither
name told you which was which, and both start with the same idea, so people opened the wrong one.

WHY THE REMOVAL. The FOLLOW-UPS heading and its two items, Follow-ups and Cadence & emails, were
added on 2026-08-06 with a nine-line comment arguing that chasing is its own job and deserves its
own section. Four days later Hanz wanted the clutter gone. He was told in as many words that
removing both leaves the cadence page with nothing linking to it, and chose that anyway, so
/followup-settings.html is now reachable by URL only.

THE BOARD CAME BACK ON 2026-08-24, and half of this file's subject is now a reversal rather than a
removal. Automated follow-ups went live on production that day and Hanz said: "make sure all follow
up emails are shown in the Chat box and in the Follow Ups section." /followups.html is linked again,
under Sales beside Active Projects. The heading did not come back. The assertion below was
INVERTED, not deleted, because the 2026-08-10 quote is still in the repo and a reader who finds only
that quote unlinks the page for a third time.

The cadence page stayed where 2026-08-11 put it, under Settings, and everything this file says
about it still holds.

"Unlinked" is one keystroke away from "deleted", which is the mistake these tests exist to catch.
The cadence page is the ONLY place the wording of four recurring customer emails is editable, it
saves by REPLACING the whole single row with no history (see test_followup_settings_page.py), and
nothing on screen points at it any more. So the last tests here assert both pages are still on
disk and still load their script, because a later cleanup pass that sees an unreferenced page and
deletes it would destroy that wording with no way back.

WHY SOURCE ASSERTIONS. The sidebar is built by string concatenation in a browser file. What is
checkable here is the markup it emits, which is exactly what changed.

THREE TESTS ELSEWHERE ASSERTED THE DELETED SECTION and were dealt with in the same commit, since
leaving them red would have meant shipping a red suite. test_followups_page.py's two sidebar tests
(test_the_board_and_its_cadence_share_one_sidebar_section and
test_neither_follow_up_page_is_left_behind_in_its_old_section) are gone, replaced by a comment
pointing here. test_followup_settings_page.py::test_the_sidebar_links_to_it_without_a_duplicate_glyph
kept its glyph half and lost its sidebar-link half, and is now
test_no_two_sidebar_items_share_a_glyph.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
AUTH = FRONTEND / "auth.js"


def _code(path):
    """Source with // comment lines stripped.

    auth.js explains this change by quoting the old labels back at you, so a raw grep for
    "Customer Portal CRM" matches the comment that records its removal and every "the old label is
    gone" assertion passes for the wrong reason. That has caught me out repeatedly in this repo.
    """
    return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                     if not l.strip().startswith("//"))


def _block(path, fn):
    """The body of a `function fn(...) {` in <path>, brace-counted.

    Never grep the whole of auth.js for a nav href: injectSidebarStyles is one enormous template
    literal and the file also holds the login and notification code, so a file-wide match proves
    nothing about the sidebar. Every assertion below is scoped to the function that must contain
    it.
    """
    src = _code(path)
    m = re.search(r"\n\s{2,6}(?:async\s+)?function " + re.escape(fn) + r"\s*\(", src)
    assert m, "%s() is gone from %s, so these tests need rewriting rather than deleting" % (
        fn, path.name)
    i = src.index("{", m.end())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    pytest.fail("unbalanced braces reading %s() in %s" % (fn, path.name))


@pytest.fixture(scope="module")
def sidebar():
    return _block(AUTH, "renderSidebar")


def _nav_labels(sidebar):
    """(href, glyph, label) for every navItem call in the sidebar."""
    return re.findall(r'navItem\("([^"]+)",\s*"([^"]+)",\s*"([^"]+)"', sidebar)


# ── the two renames ───────────────────────────────────────────────────────────
def test_the_projects_item_is_labelled_proposals_database(sidebar):
    """Kills reverting the label to "Projects", and kills renaming the page by changing its href
    instead: /projects.html is what the notification links point at and what staff have bookmarked.

    It is no longer where sign-in lands. HOME_PAGE became /portal.html on 2026-08-12 — Hanz: "tHE
    DEFAULT page when I go in to propsals.wetreadwel should be the Active projects CRM not he
    databgase" — so that half of this note would now be false. test_home_is_active_projects.py owns
    the landing page, including that the server redirect and HOME_PAGE agree."""
    assert re.search(r'navItem\("/projects\.html",\s*"[^"]+",\s*"Proposals Database"\)', sidebar), (
        "the Proposals Database item is missing; nav items are %s" % (_nav_labels(sidebar),))


def test_the_portal_item_is_labelled_active_projects(sidebar):
    """Kills reverting to "Customer Portal CRM". The href must stay /portal.html: the follow-ups
    board, the notification bell and projects.js all link into that page."""
    assert re.search(r'navItem\("/portal\.html",\s*"[^"]+",\s*"Active Projects"\)', sidebar), (
        "the Active Projects item is missing; nav items are %s" % (_nav_labels(sidebar),))


def test_no_sidebar_item_still_carries_an_old_name(sidebar):
    """Kills the half-rename: adding the new label somewhere while the old one survives, which is
    how you end up with two entries that read like two different pages."""
    labels = [lbl for _, _, lbl in _nav_labels(sidebar)]
    assert "Projects" not in labels, "the old bare 'Projects' label is still in the sidebar"
    assert "Customer Portal CRM" not in labels, "the old 'Customer Portal CRM' label survives"


# ── the follow-ups section: removed, then put back ────────────────────────────
def test_the_follow_ups_board_IS_in_the_sidebar_again(sidebar):
    """INVERTED ON 2026-08-24, and inverted rather than deleted, because Hanz reversed himself.

    This test asserted "/followups.html" was NOT in the sidebar from 2026-08-10, when he said
    "Remove the followups on the sidebar", until 2026-08-24, when automated follow-ups went live on
    production and he said: "make sure all follow up emails are shown in the Chat box and in the
    Follow Ups section." A section with no link is not a section, so the board went back in.

    Kept pointed at the same line for the same reason the Info Sheet inversion was
    (test_board_is_the_main_tab.py): the quote behind the removal is still in the repo, and a reader
    who finds only that quote removes the row again. Both quotes are in auth.js, at the navItem and
    at the note where the old FOLLOW-UPS heading used to be.

    What did NOT come back is the heading, which is the next test down."""
    assert "/followups.html" in sidebar, (
        "the Follow-ups board is unlinked again. Hanz asked for it back on 2026-08-24; if it is "
        "coming out once more, that is a new decision and this test is where to record it.")
    assert re.search(r'navItem\("/followups\.html",\s*"[^"]+",\s*"Follow-ups"\)', sidebar), (
        "the Follow-ups item is not shaped like its neighbours; nav items are %s"
        % (_nav_labels(sidebar),))


def test_the_follow_ups_board_sits_under_sales_with_active_projects(sidebar):
    """Where it went back, and why that is not arbitrary.

    It is the same population as Active Projects read a different way, and its own rows navigate
    INTO that page (/portal.html?open=...&sec=followup). Filing it anywhere else would put the link
    under one heading and land the click under another. Not under Proposals: that heading is the
    pages that MAKE a proposal, and this one starts after the proposal has gone out."""
    i = sidebar.index('tw-section">Sales')
    j = sidebar.index("/followups.html")
    assert j > i, "the Follow-ups link is above the Sales heading, so it reads as part of nothing"
    nxt = sidebar.find('tw-section">', i + 1)
    assert nxt == -1 or j < nxt, "the Follow-ups link fell out of the Sales section"
    assert sidebar.index("/portal.html") < j, "Active Projects is no longer the first Sales item"


def test_the_cadence_page_IS_still_in_the_sidebar(sidebar):
    """The board went, the cadence stayed.

    This test asserted the opposite for a few hours. Hanz first said "Remove the followups on the
    sidebar" and, asked where the orphaned cadence should go, chose to drop it too. Seeing both
    gone he reversed it: "Keep the Cadence and EMAILs... Just the follow up tab."

    Worth keeping pointed at, because unlinking this page is not a cosmetic act: it is the only
    editor for the four recurring customer emails, and its save replaces the single settings row
    with no history. An unreachable version of it is one wording change away from being
    unrecoverable.
    """
    assert "/followup-settings.html" in sidebar, "Auto Followups has left the sidebar again"


def test_the_cadence_page_is_called_auto_followups(sidebar):
    """Hanz, 2026-08-11: "Rename the cadence and emails to 'Auto Followups'". "Cadence" is a
    word from the scheduling code, not from anyone's day: what the page configures is the
    emails that go out on their own. The page's own title and heading match, or the sidebar
    sends you somewhere that calls itself something else."""
    import pathlib
    assert "Auto Followups" in sidebar, "the sidebar still uses the old cadence wording"
    assert "Cadence" not in sidebar
    page = (pathlib.Path(__file__).resolve().parents[2]
            / "frontend" / "followup-settings.html").read_text(encoding="utf-8")
    assert "<h1>Auto Followups</h1>" in page, "the page heading was not renamed with the link"
    assert "<title>Auto Followups" in page, "the browser tab still says cadence"


def test_the_cadence_page_sits_under_settings(sidebar):
    """Not under a one-item FOLLOW-UPS heading, and not stranded in Proposals. Beside
    Notification Sending, which answers the other half of the same question."""
    i = sidebar.index('tw-section">Settings')
    assert sidebar.index("/followup-settings.html") > i, (
        "the cadence link is above the Settings heading, so it reads as part of another section")
    nxt = sidebar.find('tw-section">', i + 1)
    if nxt != -1:
        assert sidebar.index("/followup-settings.html") < nxt, (
            "the cadence link fell past the end of the Settings section")


def test_the_follow_ups_heading_did_not_come_back_with_the_item(sidebar):
    """Originally: kills deleting the two items and leaving an empty FOLLOW-UPS heading behind.

    Still asserted after the 2026-08-24 reversal, and now it earns its keep from the other
    direction. The board is linked again but its two old neighbours are not coming back to sit under
    this heading: the cadence is settled under Settings and there never was a third item. Restoring
    the heading would put ONE row under a section label, which is the clutter of 2026-08-10 rebuilt
    with fewer items. The board's home is Sales, asserted above."""
    assert 'tw-section">Follow-ups' not in sidebar, (
        "the FOLLOW-UPS heading is back with one item under it; the board lives under Sales")


def test_the_removal_did_not_take_its_neighbours_with_it(sidebar):
    """The section sat between Polish Estimate and the Analytics heading, so an over-wide delete
    lands on those. Kills losing the last item of Proposals or the whole Analytics heading.

    Polish Estimate's href became /polish-intake.html on 2026-08-17 — the beta's own step 1, after
    the job conditions moved onto its intake form. Matched on the LABEL here rather than the path,
    because what this test is about is the item still being in the list, not where it goes."""
    assert '"Polish Estimate"' in sidebar, "Polish Estimate was removed along with the section"
    assert 'tw-section">Analytics' in sidebar, "the Analytics heading went with the section"
    assert sidebar.index('"Polish Estimate"') < sidebar.index('tw-section">Analytics'), (
        "Proposals and Analytics have been reordered, which was not part of this change")


def test_analytics_sits_above_the_database(sidebar):
    """Hanz, 2026-08-15: "move Analytics above the Proposal Database Please".

    Both are look-back sections rather than steps in a day, so nothing about the page breaks if
    they swap — which is exactly why the order needs an assertion. Nothing pinned it before, so
    the previous arrangement could have come back on any edit to this function."""
    assert sidebar.index('tw-section">Analytics') < sidebar.index('tw-section">Database'), (
        "the Database heading is back above Analytics")
    # And the item still belongs to its own heading rather than drifting under the other one.
    assert (sidebar.index('tw-section">Analytics')
            < sidebar.index("/analytics.html")
            < sidebar.index('tw-section">Database')), "Analytics is filed under the wrong heading"


# ── unlinked must not become deleted ──────────────────────────────────────────
@pytest.mark.parametrize("page,script", [
    ("followup-settings.html", "/js/followup-settings.js"),
    ("followups.html", "/js/followups.js"),
])
def test_the_page_still_exists_and_still_loads_its_script(page, script):
    """Kills the cleanup pass that spots an unreferenced page and deletes it, and kills the subtler
    version where the html survives but its <script src> or the js file behind it does not, so the
    page opens as an empty shell.

    The cadence page is the only editor for four recurring customer emails and saving replaces the
    whole row with no history, so losing it loses wording nobody can retype.

    Only the CADENCE page is URL-only now; the board was relinked on 2026-08-24. Both stay in this
    parametrize: the board was unlinked for a fortnight and could be again, and this pair of
    assertions is what keeps "unlinked" from sliding into "deleted" while nobody is looking.
    """
    html_path = FRONTEND / page
    assert html_path.is_file(), "%s has been deleted; it is unlinked, not unwanted" % page
    html = html_path.read_text(encoding="utf-8")
    assert 'src="%s"' % script in html, "%s no longer loads %s" % (page, script)
    js_path = FRONTEND / script.lstrip("/")
    assert js_path.is_file(), "%s is gone, so %s opens as an empty shell" % (script, page)
    assert len(js_path.read_text(encoding="utf-8")) > 500, "%s has been emptied out" % script
    # CSP: an inline <script> silently fails, so a page kept alive by inlining its JS is dead.
    assert "<script>" not in html.replace("<script src", "<script-src")


# ── the traps ─────────────────────────────────────────────────────────────────
def test_the_active_highlight_is_decided_by_the_href_not_the_label():
    """navItem marks the current page. Kills any version that compares the LABEL against the
    path, because then renaming Projects to Proposals Database would silently stop the sidebar
    highlighting the page you are standing on.
    """
    body = _block(AUTH, "navItem")
    m = re.search(r"active\s*=\s*location\.pathname", body)
    assert m, "the active check no longer starts from location.pathname"
    decision = body[m.start():body.index(";", m.start())]
    assert "href" in decision, "the active item is not decided from its href"
    assert "label" not in decision, (
        "the active highlight reads the label, so renaming an item breaks it")


def test_no_two_sidebar_items_share_a_glyph(sidebar):
    """Same invariant test_polish_estimate_page.py and test_library.py assert. Removing ⏱ and ⏲
    frees two glyphs, and this kills quietly reusing one on a new item: the icons are the only
    thing distinguishing eleven near-identical rows at a glance.
    """
    glyphs = [g for _, g, _ in _nav_labels(sidebar)]
    assert len(glyphs) == len(set(glyphs)), "two sidebar items share a glyph: %s" % glyphs


# ── the page must not disagree with the sidebar ───────────────────────────────
def test_the_projects_page_calls_itself_what_the_sidebar_calls_it():
    """Kills renaming the sidebar alone. Clicking "Proposals Database" and landing on a page
    headed "Projects" reads as the wrong page, and the browser tab is how staff find it among a
    dozen open tabs.
    """
    html = (FRONTEND / "projects.html").read_text(encoding="utf-8")
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)      # the comment records the old name
    assert "<h1>Proposals Database</h1>" in html, "the page heading was not renamed"
    assert "<h1>Projects</h1>" not in html
    assert "<title>Proposals Database" in html, "the browser tab still says Projects"


def test_the_portal_page_calls_itself_what_the_sidebar_calls_it():
    """The half of the rename that was missed the first time round: the sidebar said Active
    Projects while the page it opened was still headed and tabbed "Customer Portal CRM", which
    reads as having clicked the wrong thing. Same reason as the test above, and the tab title
    matters more here because this is the page Troy leaves open all day.
    """
    html = (FRONTEND / "portal.html").read_text(encoding="utf-8")
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)      # the comment records the old name
    assert "<h1>Active Projects</h1>" in html, "the page heading was not renamed"
    assert "Customer Portal CRM" not in html, (
        "the old name survives on the page the sidebar calls Active Projects")
    assert "<title>Active Projects" in html, "the browser tab still says Customer Portal CRM"
