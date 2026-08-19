"""The client half: a denied tab leaves the menu, and a denied page refuses instead of painting.

Hanz, 2026-08-19: "I cant toggle these on and off?" — and, asked, he chose real blocking rather than
hiding the link. So the sidebar and the server's gate have to be the same policy, and the page a
denied member lands on has to say something rather than render half of itself.

EXECUTED, NOT GREPPED, and the reason is specific: an `indexOf` call is visible in a diff, but
"a denied path leaves THAT role's menu and stays in everybody else's" is not — and neither is a
refusal card that gets painted and then overwritten. So frontend/auth.js runs in a bare VM context
(backend/tests/js/nav-permissions-harness.js), is asked for each role's sidebar under a policy, and
is then taken all the way through init() with a stubbed Supabase and a stubbed /api/me.

Nothing here duplicates test_role_visibility_matrix.py, which owns the claim that the matrix IS the
menu with no policy in play. This file is about what a policy does to it.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "nav-permissions-harness.js"

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


def _hrefs(entries):
    return [e["href"] for e in entries]


# ── the menu ──────────────────────────────────────────────────────────────────
@needs_node
def test_a_denied_path_leaves_that_roles_menu(ran):
    """The policy denies members the Lead Inbox and the Polish beta, and nothing else."""
    before, after = _hrefs(ran["menusOpen"]["user"]), _hrefs(ran["menus"]["user"])
    assert set(before) - set(after) == {"/leads.html", "/polish-intake.html"}, (
        "member menu went from %s to %s" % (before, after))
    assert after == [h for h in before if h not in ("/leads.html", "/polish-intake.html")], (
        "filtering the menu also reordered it")


@needs_node
def test_it_stays_in_every_other_roles_menu(ran):
    """The failure this kills is a filter applied to the render rather than to the role — which
    passes any test that only looks at the role that was denied something."""
    assert "/leads.html" in _hrefs(ran["menus"]["admin"])
    assert "/leads.html" in _hrefs(ran["menus"]["super_admin"])
    assert "/polish-intake.html" in _hrefs(ran["menus"]["admin"])
    # And the ADMIN's own denial is the one missing from the admin menu, nobody else's.
    assert "/history.html" not in _hrefs(ran["menus"]["admin"])
    assert "/history.html" in _hrefs(ran["menus"]["user"])
    assert "/history.html" in _hrefs(ran["menus"]["super_admin"])


@needs_node
def test_the_sections_survive_a_removed_item(ran):
    """A section heading whose only item is gone would print an empty group. Leads & bids keeps two
    of its three here, so this is about the heading still belonging to the items that remain."""
    user = ran["menus"]["user"]
    for e in user:
        assert e["section"], "%s lost its section heading" % e["href"]
    lb = [e["href"] for e in user if e["section"] == "Leads & bids"]
    assert lb == ["/crm.html", "/calendar.html"], lb


@needs_node
def test_the_super_admin_menu_is_never_short(ran):
    """nav_access.py strips his role on write AND on read, so his render always holds every row —
    which is also what guarantees navMatrix can draw a switch for a tab denied to everybody else."""
    assert _hrefs(ran["menus"]["super_admin"]) == _hrefs(ran["menusOpen"]["super_admin"])


# ── the matrix ────────────────────────────────────────────────────────────────
@needs_node
def test_the_matrix_reflects_stored_denials(ran):
    """The switches and the ticks have to be one render, or the Admin page shows a switch that is on
    beside a dash that says it is off."""
    rows = {r["href"]: r for r in ran["matrixDenied"]}
    assert rows["/leads.html"]["roles"] == {"user": False, "admin": True, "super_admin": True}
    assert rows["/history.html"]["roles"] == {"user": True, "admin": False, "super_admin": True}
    assert rows["/trash.html"]["roles"] == {"user": True, "admin": True, "super_admin": True}


@needs_node
def test_a_row_survives_being_denied_to_two_roles_out_of_three(ran):
    """Rows are created walking the most privileged role first, so a tab nobody but the super admin
    can see still HAS a row — without which the Admin page could not offer a switch to turn it back
    on, which is the one thing the page exists for."""
    rows = {r["href"]: r for r in ran["matrixDenied"]}
    assert len(rows) == len(ran["matrixOpen"]), (
        "the matrix lost %d rows to the policy"
        % (len(ran["matrixOpen"]) - len(rows)))
    assert rows["/leads.html"]["label"] == "Lead Inbox", "the row kept its label"


@needs_node
def test_with_nothing_denied_the_matrix_is_what_it_always_was(ran):
    """The no-op guarantee on the client side. Only the Admin tab differs by role."""
    differing = [r for r in ran["matrixOpen"]
                 if len({r["roles"][x] for x in ran["roles"]}) > 1]
    assert [r["href"] for r in differing] == ["/admin.html"], (
        "the role gates changed with no policy in force: %s"
        % [(r["href"], r["roles"]) for r in differing])


@needs_node
def test_the_stored_policy_drives_the_menu_and_the_matrix_with_no_argument(ran):
    """The ordinary page path: /api/me hands the denials in once and everything downstream reads
    them, rather than each caller having to remember to pass them."""
    assert {r["href"]: r["roles"] for r in ran["matrixStored"]}["/leads.html"]["user"] is False
    assert "/leads.html" not in _hrefs(ran["menuStored"])
    # And clearing it puts everything back — the way back has to exist.
    assert {r["href"]: r["roles"] for r in ran["matrixCleared"]}["/leads.html"]["user"] is True


# ── the refusal ───────────────────────────────────────────────────────────────
@needs_node
def test_a_denied_page_paints_a_refusal_instead_of_itself(ran):
    r = ran["signedIn"]["denied"]
    assert r["refusals"] == 1, "no refusal card was painted"
    assert r["emptied"] == 1, "the page's own content was left underneath the card"


@needs_node
def test_the_refusal_names_the_tab_who_can_fix_it_and_that_nothing_was_lost(ran):
    """Not "Access denied" and not a bare redirect. Somebody bounced silently thinks their click did
    not register; somebody who lands on a bare refusal with no explanation files a bug."""
    html = ran["signedIn"]["denied"]["refusalHtml"]
    assert "Lead Inbox isn't available on your account." in html, html
    assert "An admin can turn it on for members from the Admin page." in html
    assert "Nothing you were doing was lost." in html
    assert "Access denied" not in html
    assert 'href="/portal.html"' in html, "the card is a dead end with no way out"


@needs_node
def test_the_refusal_names_the_tab_that_owns_the_page_not_the_page(ran):
    """The Polish beta's step 2 has its own URL and no sidebar row. The card has to say "Polish
    Estimate", which is the tab a member would look for on the Admin page."""
    r = ran["signedIn"]["deniedStepTwo"]
    assert r["refusals"] == 1
    assert "Polish Estimate isn" in r["refusalHtml"], r["refusalHtml"]
    assert "Polish Estimate isn" in r["title"]


@needs_node
def test_the_refusal_leaves_the_sidebar_up(ran):
    """So it is not a dead end: every tab they DO have is one click away, and the filtered menu is
    itself the explanation of what they have."""
    r = ran["signedIn"]["denied"]
    assert r["sidebars"] == 1, "the refusal page has no menu"
    assert "/leads.html" not in _hrefs(r["entries"])
    assert "/trash.html" in _hrefs(r["entries"])


@needs_node
def test_nothing_boots_after_a_refusal(ran):
    """TWAuth.ready NEVER SETTLES on the refusal path, and that is the mechanism rather than an
    oversight. Every page module begins `await window.TWAuth.ready` and shared.js's API helper awaits
    it too, so nothing runs against the document the card just replaced. Resolving instead means each
    page's boot continues, finds its elements gone, and either throws or paints an empty shell back
    over the card."""
    assert ran["signedIn"]["denied"]["ready"] == "pending", (
        "ready settled after a refusal, so the page's own boot is about to run")
    assert ran["signedIn"]["deniedStepTwo"]["ready"] == "pending"


@needs_node
def test_an_allowed_page_boots_exactly_as_before(ran):
    """The other half of the same claim: a member denied SOMETHING must not have every page held up."""
    r = ran["signedIn"]["allowed"]
    assert r["ready"] == "settled"
    assert r["refusals"] == 0 and r["emptied"] == 0
    assert r["sidebars"] == 1


@needs_node
def test_a_role_denied_something_else_is_not_refused_here(ran):
    """The admin is denied History and is standing on /leads.html. Refusing them would mean the
    check reads "is anything denied" rather than "is THIS page denied"."""
    r = ran["signedIn"]["otherRole"]
    assert r["role"] == "admin"
    assert r["refusals"] == 0 and r["ready"] == "settled"
    assert r["deniedPaths"] == ["/history.html"]


@needs_node
def test_a_response_that_says_nothing_about_permissions_denies_nothing(ran):
    """The deploy window, and the fail-open rule on the client. A container that predates this
    feature — or one whose policy read failed — answers /api/me with no nav_denied at all, and every
    tab has to stay where it was."""
    r = ran["signedIn"]["legacy"]
    assert r["deniedPaths"] == []
    assert r["refusals"] == 0 and r["ready"] == "settled"
    assert len(r["entries"]) == len(ran["menusOpen"]["user"]), (
        "a member with no policy saw %d tabs instead of %d"
        % (len(r["entries"]), len(ran["menusOpen"]["user"])))


# ── the switches ──────────────────────────────────────────────────────────────
@needs_node
def test_the_capability_table_the_harness_uses_is_the_one_the_server_serves(ran):
    """Everything below is checked against a policy this harness declares. Declared copies rot, so it
    is diffed against backend/nav_access.py rather than trusted."""
    import nav_access
    # href / label / api / locked are the four fields the panel reads. `pages` is deliberately not
    # compared here: nothing on this page uses it — it drives the refusal card, which
    # test_the_refusal_names_the_tab_that_owns_the_page_not_the_page covers instead.
    keys = ("href", "label", "api", "locked")
    want = [{k: t[k] for k in keys} for t in nav_access.capability_table()]
    assert ran["caps"] == want, (
        "the harness's copy of the capability table has drifted from nav_access.py")


@needs_node
@pytest.mark.parametrize("viewer", ["user", "admin", "super_admin"])
def test_every_cell_is_a_switch_carrying_its_own_state(ran, viewer):
    """The tick lives INSIDE the button, so a cell cannot show a switch that is on beside a dash that
    says it is off — there is only one thing to read. aria-pressed carries it for a screen reader."""
    for row in ran["panel"][viewer]:
        for role in ran["roles"]:
            sw = row["switches"][role]
            assert sw, "%s / %s has no switch" % (row["href"], role)
            assert sw["href"] == row["href"] and sw["role"] == role, (
                "%s / %s carries the wrong identity: %s" % (row["href"], role, sw))
            assert sw["on"] == row["roles"][role], (
                "%s / %s: the switch says %s and the tick says %s"
                % (row["href"], role, sw["on"], row["roles"][role]))
            assert sw["pressed"] == ("true" if sw["on"] else "false")
            assert sw["dataOn"] == ("1" if sw["on"] else "0")


@needs_node
def test_the_switches_reflect_the_stored_policy(ran):
    """Not "every switch is on": the ticks and the switches are one render of the sidebar under the
    policy, which is what stops them disagreeing."""
    rows = {r["href"]: r for r in ran["panel"]["admin"]}
    assert rows["/leads.html"]["switches"]["user"]["on"] is False
    assert rows["/leads.html"]["switches"]["admin"]["on"] is True
    assert rows["/history.html"]["switches"]["admin"]["on"] is False
    assert rows["/history.html"]["switches"]["user"]["on"] is True
    assert rows["/trash.html"]["switches"]["user"]["on"] is True


@needs_node
@pytest.mark.parametrize("href", ["/admin.html", "/portal.html"])
def test_a_locked_page_cannot_be_switched_off_for_anybody(ran, href):
    """/admin.html is where this setting is edited and /portal.html is where signing in lands. The
    server strips both on write AND on read; the UI must not offer what the server will refuse."""
    rows = {r["href"]: r for r in ran["panel"]["admin"]}
    row = rows[href]
    assert row["chip"] == "lock", "%s does not say it cannot be denied" % href
    for role in ran["roles"]:
        assert row["switches"][role]["disabled"] is True, "%s / %s is clickable" % (href, role)


@needs_node
@pytest.mark.parametrize("viewer", ["user", "admin", "super_admin"])
def test_the_super_admin_column_is_never_clickable(ran, viewer):
    """That role is bootstrapped from the server's environment and is the account that always has a
    way in. nav_access.py strips it on write and on read, so a switch there would save nothing."""
    for row in ran["panel"][viewer]:
        assert row["switches"]["super_admin"]["disabled"] is True, row["href"]
        assert row["switches"]["super_admin"]["on"] is True, (
            "%s is off for the super admin, who cannot be denied anything" % row["href"])


@needs_node
def test_a_viewer_cannot_switch_their_own_role_off_but_can_switch_it_back_on(ran):
    """The server refuses the first and allows the second, and the UI says the same thing — a switch
    that looks clickable and then fails is worse than one that explains itself on hover."""
    rows = {r["href"]: r for r in ran["panel"]["admin"]}
    own_on = rows["/trash.html"]["switches"]["admin"]
    assert own_on["on"] is True and own_on["disabled"] is True
    assert "own role" in own_on["title"], own_on["title"]
    # /history.html is already denied to admins, so turning it back on is widening — always allowed.
    own_off = rows["/history.html"]["switches"]["admin"]
    assert own_off["on"] is False and own_off["disabled"] is False
    # And a member's switches stay editable for that same admin viewer.
    assert rows["/trash.html"]["switches"]["user"]["disabled"] is False


@needs_node
def test_the_five_tabs_with_no_private_endpoint_say_so_on_screen(ran):
    """Derived from the capability table, so the claim cannot outlive the code. Switching one of these
    off hides the tab and blocks the page and leaves the data reachable — and the page must SAY that
    rather than imply a lock it does not have."""
    caps = {c["href"]: c for c in ran["caps"]}
    rows = {r["href"]: r for r in ran["panel"]["admin"]}
    thin = [h for h, c in caps.items() if not c["api"] and not c["locked"]]
    hard = [h for h, c in caps.items() if c["api"]]
    assert thin, "no tab owns zero private endpoints any more; the wording below should go"
    for href in thin:
        assert rows[href]["chip"] == "thin", "%s does not say a switch there only hides it" % href
        title = rows[href]["switches"]["user"]["title"]
        assert "hides the tab and blocks the page" in title, title
        assert "reachable to somebody who types the URL" in title, title
    for href in hard:
        assert rows[href]["chip"] == "hard", "%s does not say a switch there blocks its data" % href
        assert caps[href]["api"][0] in rows[href]["switches"]["user"]["title"], (
            "%s does not name the routes it refuses" % href)
    # And the note names them, computed from the same table.
    flat = re.sub(r"\s+", " ", ran["panelHtml"]["admin"])
    assert "can only be hidden, not sealed" in flat
    for href in thin:
        assert "<strong>%s</strong>" % caps[href]["label"] in flat, (
            "%s is not named in the note" % href)


@needs_node
def test_the_note_still_says_the_page_itself_stays_served(ran):
    """The honest half of "real blocking". There is no cookie in this app, so a browser navigating to
    a page carries no identity — the .html serves and paints a refusal. Somebody reading this table as
    "the URL is sealed" would be wrong, and the page has to say which it is."""
    flat = re.sub(r"\s+", " ", ran["panelHtml"]["admin"])
    assert "reachable by typing its URL" in flat
    assert "refusal card" in flat
    assert "not a permission model" in flat
    assert "_require_admin" in flat


@needs_node
def test_a_failed_policy_fetch_renders_read_only_and_says_so(ran):
    """A panel full of switches that save nothing is worse than a table. The deny map alone is not
    enough — without the capability table the page cannot tell which switches only hide."""
    assert not any(v for r in ran["readOnlyRows"] for v in r["switches"].values()), (
        "switches were drawn with no capability table to describe them")
    assert "Read-only right now" in re.sub(r"\s+", " ", ran["readOnlyHtml"])
    # It still shows the truth about the policy that IS loaded.
    rows = {r["href"]: r for r in ran["readOnlyRows"]}
    assert rows["/leads.html"]["roles"]["user"] is False


@needs_node
def test_with_no_policy_at_all_the_panel_is_exactly_the_old_read_only_table(ran):
    """The state test_role_visibility_matrix.py owns, and the state a container with no policy file is
    in. No switches, no chips, and only the Admin tab differing by role."""
    assert not any(v for r in ran["noPolicyRows"] for v in r["switches"].values())
    assert not any(r["chip"] for r in ran["noPolicyRows"])
    differing = [r["href"] for r in ran["noPolicyRows"]
                 if len({r["roles"][x] for x in ran["roles"]}) > 1]
    assert differing == ["/admin.html"], differing


# ── the wiring ────────────────────────────────────────────────────────────────
def test_the_toggle_is_wired_and_the_panel_re_renders_in_place():
    """The CSP forbids inline handlers, so a switch with no addEventListener silently does nothing —
    and a save that does not re-render leaves the table showing the state before the click."""
    js = (FRONTEND / "js" / "admin.js").read_text(encoding="utf-8")
    assert 'document.querySelectorAll(\'#rv-panel [data-act="nav"]\')' in js, (
        "the switches are never wired up")
    assert "el.outerHTML = roleMatrixHtml()" in js, "a save does not re-render the panel"
    assert "wireRoleMatrix()" in js and js.count("wireRoleMatrix()") >= 3, (
        "the re-rendered panel is never re-wired, so the second click does nothing")
    assert "onclick=" not in js.lower()


def test_the_policy_is_fetched_before_the_first_paint():
    """Rendering first and correcting afterwards means every switch flashes on. The matrix is built by
    re-rendering the sidebar per role, so TWAuth has to be holding the policy before shell() runs."""
    js = (FRONTEND / "js" / "admin.js").read_text(encoding="utf-8")
    assert js.index("await loadNavPolicy()") < js.index("shell();"), (
        "shell() renders the matrix before the policy is loaded")
    assert "TWAuth.setNavDeny" in js, (
        "the page never hands the full per-role map to auth.js, so the matrix can only show its own")


def test_the_refusals_reason_reaches_the_user():
    """"You can't take that away from your own role" is actionable. "Action failed" sends somebody to
    the logs — and api() throws the status away, which is why this route uses its own caller."""
    js = (FRONTEND / "js" / "admin.js").read_text(encoding="utf-8")
    assert "async function apiFull(" in js
    assert "res.body.detail" in js or "body.detail" in js, (
        "a 400 from FastAPI carries its reason in `detail`, and nothing reads it")
    assert "alert(errText(res))" in js


def test_the_switch_and_its_chips_are_styled_and_hideable():
    """Unstyled, every switch is a bare button in a nowrap cell. And `hidden` works through one UA
    rule with the lowest specificity there is, so any class rule setting `display` beats it — the
    guard ships with the rule (backend/tests/test_hidden_is_actually_hidden.py)."""
    html = (FRONTEND / "admin.html").read_text(encoding="utf-8")
    for cls in (".rv-sw {", ".rv-sw.rv-on {", ".rv-sw:disabled {", ".rv-lock,", ".rv-thin {",
                ".rv-hard {"):
        assert cls in html, "%s has no styling" % cls
    assert re.search(r"\.rv-sw\[hidden\][^{]*\{[^}]*display\s*:\s*none", html), (
        "the switch sets display and has no [hidden] guard")
    # CSP: an inline <script> would silently not run, so the panel must stay in admin.js.
    assert "<script>" not in html.replace("<script src", "<script-src")


# ── the card is actually styled ───────────────────────────────────────────────
def test_the_refusal_card_has_styles_and_they_live_with_the_sidebar():
    """auth.js's injected stylesheet is the only CSS every page has, and the card is painted onto
    pages whose own <style> block was just thrown away — so styling it anywhere else means it renders
    as unstyled text on most of the app."""
    js = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    for cls in (".tw-refuse{", ".tw-refuse-card{", ".tw-refuse-h{", ".tw-refuse-p{",
                ".tw-refuse-go{"):
        assert cls in js, "%s has no rule, so the refusal renders as a wall of text" % cls
    # The stylesheet is one long template literal. A backtick anywhere in it — a comment included —
    # silently ends the string and takes auth.js off the air, and auth.js is what mints the token.
    css = js[js.index("const css = `") + len("const css = `"):]
    css = css[:css.index("`;")]
    assert "tw-refuse" in css
    assert "`" not in css


def test_the_refusal_copy_lives_in_exactly_one_place():
    """One string, so a wording change cannot leave two versions of it in the app."""
    js = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    assert js.count("Nothing you were doing was lost.") == 1
    hits = [p.name for p in list(FRONTEND.glob("*.html")) + list((FRONTEND / "js").glob("*.js"))
            if "Nothing you were doing was lost" in p.read_text(encoding="utf-8")]
    assert hits == [], "the refusal copy is duplicated in %s" % hits


def test_the_denied_page_list_comes_only_from_the_server():
    """One sidebar row owns TWO pages, because the Polish beta's step 2 is opened from doors that are
    not the menu. auth.js must not carry a second copy of that expansion — it is the copy that goes
    stale the day a third door appears — so DENIED_PAGES is assigned exactly twice: its declaration,
    and straight out of the /api/me response."""
    js = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    assigns = re.findall(r"DENIED_PAGES\s*=\s*(.+)", js)
    assert len(assigns) == 2, "DENIED_PAGES is assigned %d times: %s" % (len(assigns), assigns)
    assert assigns[0].strip().startswith("{}"), assigns[0]
    assert "me.nav_denied_pages" in assigns[1], assigns[1]
    main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
    assert "_nav_denied_pages_for" in main, "the server no longer expands the page list"
