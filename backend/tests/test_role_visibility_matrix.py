"""The Admin page shows which sidebar tabs each role gets — and it is the menu, not a copy of it.

Hanz, 2026-08-19: "For the admin dashboard, can we actually show what sidebar tabs is can be
present for the admins, the members and the superadmin?"

WHY THE DERIVATION IS THE FEATURE. A table of tab names typed into admin.js would be correct on the
day it was written and wrong the first time somebody adds a page — and wrong invisibly, because
nothing about the sidebar breaks when a reference table falls behind it. So auth.js renders the
nav ONCE PER ROLE out of its own markup (TWAuth.navSpec / navMatrix) and the Admin page renders
what that reports. These tests exist to prove that claim rather than to restate it.

EXECUTED, NOT GREPPED. `frontend/auth.js` runs in a bare VM context and is asked for each role's
sidebar; `roleMatrixHtml()` is lifted out of `frontend/js/admin.js` and run against that same live
TWAuth; the rows it emits are parsed back out of the HTML. Four things then have to agree:

  * the sidebar auth.js APPENDS TO THE PAGE after a real sign-in as that role (the harness stubs
    Supabase and /api/me, so init() runs end to end and document.body.appendChild is spied on);
  * the markup spec mode hands back for the same role, character for character;
  * TWAuth.navMatrix()'s rows and ticks;
  * the rows the Admin page actually renders.

A source assertion could not reach any of it. "admin.js mentions navMatrix" says nothing about
which rows come out, and the interesting mutation — a hardcoded row list that happens to look
right — passes every grep. The probe run is the one that kills it: a copy of auth.js with two extra
navItem() calls spliced into the sidebar expression, one open and one behind the admin gate, and
NOTHING else changed. A derived table grows two rows with the right ticks. A typed one grows none.

The existing sidebar tests (test_sidebar_labels.py, test_board_is_the_main_tab.py) still own the
list itself — its labels, its order, its sections. Nothing here duplicates them.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
BACKEND = ROOT / "backend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "nav-visibility-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _key(entry):
    """What identifies a nav row, independent of who parsed it."""
    return (entry["section"], entry["href"], entry["glyph"], entry["label"], entry["tag"])


def _ticked(matrix, role):
    return [_key(r) for r in matrix["rows"] if r["roles"][role]]


# ── the roles ─────────────────────────────────────────────────────────────────
@needs_node
def test_the_matrix_covers_the_three_roles_the_backend_actually_stores(ran):
    """Not a fourth invented for the table, and not two with super_admin folded into admin.

    profiles.py stores one of exactly these three and list_users filters on the same tuple;
    _require_admin accepts the last two. A column for a role the database cannot hold would be
    fiction, and a missing column would hide somebody's real menu.
    """
    assert ran["roles"] == ["user", "admin", "super_admin"], ran["roles"]
    profiles = (BACKEND / "profiles.py").read_text(encoding="utf-8")
    assert '("user", "admin", "super_admin")' in profiles, (
        "profiles.py no longer stores these three roles, so the matrix columns have moved")
    main = (BACKEND / "main.py").read_text(encoding="utf-8")
    assert '("admin", "super_admin")' in main, (
        "_require_admin's accepted roles have changed; the matrix's admin column has moved")


# ── the matrix IS the sidebar ─────────────────────────────────────────────────
@needs_node
@pytest.mark.parametrize("role", ["user", "admin", "super_admin"])
def test_the_matrix_rows_are_exactly_the_sidebar_this_role_gets(ran, role):
    """THE assertion that makes the panel honest. The sidebar is rendered for real — signed in as
    this role, all the way to document.body.appendChild — and its items are pulled back out with
    the harness's own regex. What the matrix ticks for the role must be that list, in that order,
    with the same sections, glyphs, labels and BETA tags.

    Kills a hardcoded table (its rows drift), a matrix built from one role's render and re-labelled
    (the ticks stop matching), and a parser in auth.js that quietly drops the tag or the section
    (the tuples stop matching).
    """
    page = [_key(e) for e in ran["renderedEntries"][role]]
    assert page, "the sidebar rendered nothing for %s — the harness's sign-in path broke" % role
    assert _ticked(ran["matrix"], role) == page, (
        "the matrix disagrees with the %s sidebar\n  matrix: %s\n  sidebar: %s"
        % (role, _ticked(ran["matrix"], role), page))


@needs_node
@pytest.mark.parametrize("role", ["user", "admin", "super_admin"])
def test_spec_mode_builds_the_same_nav_the_page_gets(ran, role):
    """renderSidebar("admin") must be the sidebar an admin sees, not a plausible sibling of it.

    Compared character for character over the <nav> block. If spec mode ever read the role from
    currentUser, or evaluated a gate against the wrong thing, every other check here would still
    agree with itself — this is the one that catches it.
    """
    r = ran["rendered"][role]
    assert r["role"] == role, "signing in as %s produced role %r" % (role, r["role"])
    assert r["sidebars"] == 1, "the page render appended %d sidebars" % r["sidebars"]
    assert r["navMatches"], (
        "spec mode and the page render disagree for %s\n  page: %s\n  spec: %s"
        % (role, r["nav"], r["specNav"]))


@needs_node
@pytest.mark.parametrize("role", ["user", "admin", "super_admin"])
def test_the_panel_renders_one_row_per_tab_with_the_right_ticks(ran, role):
    """The Admin page's own roleMatrixHtml(), executed. Rows in sidebar order, every role's cell
    a tick or a dash, and a tick exactly where that role's sidebar has the item.

    Kills the panel rendering the matrix it was handed and then ticking the wrong column — a
    transposed loop reads fine in the source and is nonsense on screen.

    THE PANEL IS THE MENU PLUS THE TABS THAT ARE GATED WITHOUT BEING DRAWN. navMatrix() with no
    argument is the menu, tab for tab, and stays that (test_nav_permissions_ui.py owns that seam);
    the panel asks it about a POLICY, which also carries nav_access.NO_SIDEBAR_TABS. So the menu
    rows are compared in order and the extra rows are compared as a set — no more, no fewer, which
    is what stops the panel growing a row nothing governs.
    """
    import nav_access
    rowless = set(nav_access.NO_SIDEBAR_TABS)
    rows = ran["panel"][role]
    menu = [r for r in rows if r["href"] not in rowless]
    assert [r["href"] for r in menu] == [r["href"] for r in ran["matrix"]["rows"]]
    assert {r["href"] for r in rows} - {r["href"] for r in menu} == rowless, (
        "the panel's extra rows are not the gated-but-undrawn tabs: %s"
        % sorted({r["href"] for r in rows} - {r["href"] for r in menu}))
    # "Leads &amp; bids" on the way through the markup — the entity is the panel escaping its own
    # output, which is correct; compare the text.
    unesc = lambda s: s.replace("&amp;", "&")           # noqa: E731
    assert [unesc(r["section"]) for r in menu] == [r["section"] for r in ran["matrix"]["rows"]], (
        "the rows carry the wrong section headings")
    sections = {r["section"] for r in menu}
    for r in rows:
        if r["href"] in rowless:
            assert r["section"] in sections, (
                "%s is filed under %r, which is not a section of this menu"
                % (r["href"], r["section"]))
    # The section column prints once per group. Kills the off-by-one that blanks the FIRST row of
    # each section instead of the repeats, which loses every heading.
    for i, r in enumerate(rows):
        first_of_group = i == 0 or rows[i - 1]["section"] != r["section"]
        assert bool(r["sectionCell"]) == first_of_group, (
            "%s prints its section %r where first-of-group is %s"
            % (r["href"], r["sectionCell"], first_of_group))
        if first_of_group:
            assert unesc(r["sectionCell"]) == unesc(r["section"])
    for r in rows:
        for who in ran["roles"]:
            seen = {e["href"] for e in ran["renderedEntries"][who]}
            assert r["roles"][who] == (r["href"] in seen), (
                "%s is ticked %s for %s but the %s sidebar says otherwise"
                % (r["href"], r["roles"][who], who, who))


# ── it is derived, not typed ───────────────────────────────────────────────────
@needs_node
def test_a_new_sidebar_tab_shows_up_in_the_matrix_on_its_own(ran):
    """The probe run: a copy of auth.js with one extra navItem() spliced into the sidebar
    expression. admin.js is untouched, and nothing anywhere was told about the new page.

    This is the test that a second, hand-kept list of tabs cannot pass.
    """
    rows = {r["href"]: r for r in ran["probe"]["matrixRows"]}
    assert "/probe-open.html" in rows, (
        "a tab added to the sidebar did not reach the matrix, so the matrix is a copy of the list: "
        + ", ".join(sorted(rows)))
    probe = rows["/probe-open.html"]
    assert probe["label"] == "Probe Open"
    assert probe["tag"] == "NEW", "the BETA-style tag is dropped on the way through"
    assert all(probe["roles"].values()), "an ungated tab came out gated: %s" % probe["roles"]
    panel = {r["href"]: r for r in ran["probe"]["panelRows"]}
    assert "/probe-open.html" in panel, "the new tab reached the matrix but not the rendered panel"


@needs_node
def test_a_role_gated_tab_is_reported_as_gated_without_being_declared_anywhere(ran):
    """The second probe is wrapped in the sidebar's own isAdmin ternary. Nothing declares that it
    is admin-only — the matrix finds out by building the nav as a member and not seeing it.

    Kills a matrix that reads a required-role field somebody has to remember to fill in.
    """
    rows = {r["href"]: r for r in ran["probe"]["matrixRows"]}
    assert "/probe-gated.html" in rows, "an admin-gated tab is missing from the matrix entirely"
    assert rows["/probe-gated.html"]["roles"] == {
        "user": False, "admin": True, "super_admin": True}, rows["/probe-gated.html"]["roles"]
    panel = {r["href"]: r for r in ran["probe"]["panelRows"]}
    assert panel["/probe-gated.html"]["roles"]["user"] is False, (
        "the rendered panel ticks a member for a tab a member cannot see")


# ── accuracy over impressiveness ───────────────────────────────────────────────
@needs_node
def test_today_exactly_one_row_differs_and_it_is_the_admin_tab(ran):
    """The sidebar difference between a member and an admin is one item. The panel says so in as
    many words, and this pins it: no padding the table to look richer than reality, and no losing
    the one gate that is real.

    If a second gate is ever added this test fails and should be UPDATED, not deleted — the header
    count and the sentence under the table are computed, so they will already be telling the truth
    while this file is what still says one.
    """
    rows = ran["matrix"]["rows"]
    differing = [r for r in rows if len({r["roles"][x] for x in ran["roles"]}) > 1]
    assert [r["href"] for r in differing] == ["/admin.html"], (
        "the role gates have changed: %s" % [(r["href"], r["roles"]) for r in differing])
    assert differing[0]["roles"] == {"user": False, "admin": True, "super_admin": True}
    # And the admin/super-admin columns are identical, which is why the panel says the extra
    # super-admin powers live inside the page rather than in a tab.
    for r in rows:
        assert r["roles"]["admin"] == r["roles"]["super_admin"], (
            "%s now differs between admin and super admin; the panel's closing sentence is "
            "computed and will follow, but this test needs rewriting" % r["href"])


@needs_node
def test_the_summary_line_is_computed_from_the_rows(ran):
    """The header count and the sentence beneath the table have to move with the data, because a
    typed "only the Admin tab differs" is a claim that rots quietly.
    """
    import nav_access
    html = ran["panelHtml"]["admin"]
    total = len(ran["matrix"]["rows"])
    member = len(ran["renderedEntries"]["user"])
    # "sidebar tabs" was true until a tab could be governed without being drawn. The header counts
    # ROWS, and NO_SIDEBAR_TABS has no sidebar row, so the word came out and the count grew; the
    # panel names those tabs instead of absorbing them. test_nav_permissions_ui.py owns the wording
    # in every one of the three states this panel has.
    assert "%d tabs" % (total + len(nav_access.NO_SIDEBAR_TABS)) in html, html[:400]
    assert "sidebar tabs" not in html, (
        "the header counts a tab with no sidebar row among the sidebar tabs")
    assert re.search(r"1\s+differs by role", html), "the header does not count the differing rows"
    assert "Members see %d of the %d tabs" % (member, total) in re.sub(r"\s+", " ", html), (
        "the summary does not count what a member actually sees")
    assert "<strong>Admin</strong>" in html, "the summary does not name the tab that differs"


@needs_node
@pytest.mark.parametrize("role,label", [("user", "Member"), ("admin", "Admin"),
                                        ("super_admin", "Super admin")])
def test_the_viewer_sees_which_role_is_theirs(ran, role, label):
    """"Note in the UI which role the viewer currently has." Marked on their own COLUMN as well as
    spelled out in the header, so a row answers "and me?" without counting across.

    Rendered by the harness once per role against the real TWAuth. Kills the marker being pinned to
    a single hardcoded column — the mutation that shows every viewer "Admin — you".
    """
    html = ran["panelHtml"][role]
    assert 'class="rv-h rv-mine">%s<span class="you">you</span>' % label in html, (
        "a %s does not see which column is theirs" % label)
    assert "Your role: <strong>%s</strong>" % label in html, (
        "the panel does not name the viewer's role")
    # Exactly one column is marked — two would be worse than none.
    assert html.count("rv-mine") == 1, "%d columns are marked as the viewer's" % html.count("rv-mine")


# ── a hidden tab is not a permission ──────────────────────────────────────────
@needs_node
def test_the_panel_says_the_server_is_what_enforces_this(ran):
    """The whole risk of this table is somebody reading it as a permission model. A member who
    types /admin.html gets the page; what stops them is _require_admin on every route behind it.
    """
    flat = re.sub(r"\s+", " ", ran["panelHtml"]["admin"])
    assert "not a permission model" in flat
    assert "_require_admin" in flat, "the note does not name what actually enforces access"
    assert "reachable by typing its URL" in flat, (
        "the note does not say a hidden tab is still a reachable page")


@needs_node
def test_the_note_only_calls_auto_followups_ungated_while_it_actually_is(ran):
    """The panel names the one write that is broader than the rest: saving Auto Followups needs no
    admin, replaces the settings row with no history, and rewrites four emails that go to
    customers. Naming it is only honest while it is true — so this fails the day somebody gates
    it, and the sentence should come out with the same commit.
    """
    main = (BACKEND / "main.py").read_text(encoding="utf-8")
    i = main.index('@app.put("/api/followup-settings")')
    body = main[i:main.index("@app.", i + 10)]
    ungated = "_require_admin" not in body
    flat = re.sub(r"\s+", " ", ran["panelHtml"]["admin"])
    said = "Auto Followups is the exception" in flat
    assert ungated == said, (
        "PUT /api/followup-settings is %s but the panel says %s"
        % ("ungated" if ungated else "admin-gated", "ungated" if said else "nothing about it"))


@needs_node
def test_the_note_names_every_member_visible_tab_that_gates_controls_on_role(ran):
    """Derived, so the note cannot fall behind the code.

    Any page JS that branches on role === "admin" is gating something inside a tab everybody can
    open — the Item Library's vendor/division/unit editing, the notification roster, reassigning
    another estimator's project. The page's own sidebar entry is found by filename, so a new
    role-gated page fails this until the note names it, and a gate that is REMOVED fails it too.
    """
    labels = {r["href"]: r["label"] for r in ran["matrix"]["rows"]}
    member_visible = {r["href"] for r in ran["matrix"]["rows"] if r["roles"]["user"]}
    gated = []
    for js in sorted((FRONTEND / "js").glob("*.js")):
        src = js.read_text(encoding="utf-8")
        if not re.search(r'role\s*===\s*"admin"', src):
            continue
        href = "/" + js.stem + ".html"
        if href in member_visible:
            gated.append(labels[href])
    assert gated, "no page JS gates on role any more; the third note paragraph should go"
    flat = re.sub(r"\s+", " ", ran["panelHtml"]["admin"])
    for label in gated:
        assert "<strong>%s</strong>" % label in flat, (
            "%s gates controls on role but the note does not name it (it names: %s)"
            % (label, re.findall(r"<strong>([^<]+)</strong>", flat)))


# ── the panel is actually on the page ─────────────────────────────────────────
def test_the_admin_page_renders_the_panel_and_styles_it():
    """Kills the version that exists as a function nobody calls, and the one that renders with no
    stylesheet, where every tick and dash lands in a nowrap table cell with no alignment."""
    js = (FRONTEND / "js" / "admin.js").read_text(encoding="utf-8")
    assert "${roleMatrixHtml()}" in js, "shell() does not render the role matrix"
    i, j = js.index("${roleMatrixHtml()}"), js.index("<strong>Projects</strong>")
    assert js.index("<strong>Users</strong>") < i < j, (
        "the matrix is not between the Users and Projects panels, where the role column explains it")
    html = (FRONTEND / "admin.html").read_text(encoding="utf-8")
    for cls in (".rv-cell", ".rv-yes", ".rv-no", ".rv-note", ".rv-ico", ".rv-mine"):
        assert cls in html, "%s has no styling, so the matrix renders as a wall of text" % cls
    # CSP: an inline <script> would silently not run. The panel must stay in admin.js.
    assert "<script>" not in html.replace("<script src", "<script-src")
