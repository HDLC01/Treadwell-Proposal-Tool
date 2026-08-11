"""Where the app opens, and the one query string that must never be redirected.

Hanz, 2026-08-12: "tHE DEFAULT page when I go in to propsals.wetreadwel should be the Active
projects CRM not he databgase."

It used to be the Proposals Database, which was right while that page was the only place to mint a
draft. It stopped being right the moment the board grew a + New button, and the page the weekly
sales meeting runs on should not be something you navigate away from on arrival.

TWO PLACES DECIDE THIS, which is the whole reason this file exists. `main.py:_root` handles somebody
typing the bare domain; `auth.js`'s HOME_PAGE handles where signing in lands and where the login
page bounces an already-authenticated user. Changing one and not the other is not a visible bug —
you land on the board from a bookmark and on the Database after a fresh sign-in, and nothing looks
broken enough to investigate. So both are asserted, and asserted to AGREE.

WHY ?new IS THE DANGEROUS PART. Both the Database and the board's + New button navigate to
`/?new=1` (frontend/js/projects.js and portal.js — compared character for character in
test_board_is_the_main_tab.py). The root handler serves the intake form for `?new`/`?edit` and
redirects everything else. Move the redirect above that branch, or drop the branch while
"simplifying" the handler, and pressing + New bounces straight back to a board: there would be no
way to start a proposal at all, from anywhere in the app.

The `?d=` case is deliberate and predates this change: an old draft link left in browser history
lands on a board rather than a half-filled intake form nobody asked for.
"""
import pathlib
import re

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
AUTH_JS = (FRONTEND / "auth.js").read_text(encoding="utf-8")

HOME = "/portal.html"


def _redirect(url: str):
    return client.get(url, follow_redirects=False)


# ── the bare domain ──────────────────────────────────────────────────────────
def test_the_bare_domain_lands_on_active_projects():
    """The ask, in one assertion."""
    r = _redirect("/")
    assert r.status_code in (302, 307, 308), (
        "the root serves something inline instead of redirecting (%s)" % r.status_code)
    assert r.headers["location"] == HOME, (
        "the bare domain lands on %s" % r.headers.get("location"))


def test_an_old_draft_link_in_history_lands_on_a_board_not_a_half_filled_form():
    """Predates this change and still holds: `?d=<uuid>` is what the intake form used to leave in
    history, and resuming it from the bare root shows a form for a project nobody chose."""
    r = _redirect("/?d=00000000-0000-0000-0000-000000000000")
    assert r.status_code in (302, 307, 308)
    assert r.headers["location"] == HOME


def test_an_unknown_query_string_does_not_open_the_intake_form():
    """The branch is an allow-list of two, not a catch-all. `?utm_source=…` on a shared link must
    not open a blank New Project screen."""
    r = _redirect("/?utm_source=email&ref=slack")
    assert r.status_code in (302, 307, 308)
    assert r.headers["location"] == HOME


# ── the branch that must survive ─────────────────────────────────────────────
def test_starting_a_new_proposal_still_reaches_the_intake_form():
    """THE one that matters. `/?new=1` is what both the Proposals Database and the board's + New
    button navigate to. If this redirects, nothing in the app can start a bid."""
    r = _redirect("/?new=1")
    assert r.status_code == 200, (
        "/?new=1 returned %s — pressing + New would bounce back to a board" % r.status_code)
    assert b"<title" in r.content


def test_editing_still_reaches_the_intake_form():
    r = _redirect("/?edit=1")
    assert r.status_code == 200


def test_the_intake_form_is_served_uncached():
    """It carries a draft id in the URL and reads localStorage on boot; a cached copy is how a
    stale project appeared under a new one's id."""
    r = _redirect("/?new=1")
    cache = (r.headers.get("cache-control") or "").lower()
    assert "no-store" in cache, "the intake form is cacheable: %r" % cache


def test_the_new_branch_is_checked_BEFORE_the_redirect():
    """Asserted against the source as well as the behaviour, because the ordering is the whole
    mechanism and a reordered handler would fail every test above at once — this one says why."""
    import inspect
    src = inspect.getsource(main._root)
    assert src.index('"new" in q') < src.index("RedirectResponse"), (
        "the redirect runs before the ?new branch, so + New can never open the intake form")


# ── the other half of the decision ───────────────────────────────────────────
def test_signing_in_lands_on_the_same_page_the_bare_domain_does():
    """auth.js's HOME_PAGE is used twice: `location.replace(HOME_PAGE)` when the login page finds an
    existing session, and `redirectTo` on the OAuth round trip. Both have to agree with the server's
    redirect, or the app opens somewhere different depending on how you arrived."""
    m = re.search(r'const HOME_PAGE = "([^"]+)"', AUTH_JS)
    assert m, "HOME_PAGE is gone from auth.js — this test needs rewriting, not deleting"
    assert m.group(1) == HOME, (
        "signing in lands on %s while the bare domain lands on %s" % (m.group(1), HOME))


def test_both_uses_of_home_page_go_through_the_constant():
    """A hardcoded "/projects.html" next to the constant is how these drifted in the first place."""
    assert AUTH_JS.count("HOME_PAGE") >= 3, "HOME_PAGE is declared but barely used"
    body = AUTH_JS[AUTH_JS.index("const HOME_PAGE"):]
    assert '"/projects.html"' not in body.split("navItem")[0], (
        "the auth flow still hardcodes the old landing page alongside the constant")


def test_the_proposals_database_is_still_reachable():
    """Moved, not removed. It is where every historical draft lives, and staff have it bookmarked."""
    assert 'navItem("/projects.html"' in AUTH_JS, (
        "the Proposals Database left the sidebar; it is only supposed to have stopped being home")
