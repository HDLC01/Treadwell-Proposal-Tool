"""Where the app opens, and the one query string that must never be diverted.

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
test_board_is_the_main_tab.py). The root handler serves the intake form for `?new`/`?edit` and the
board for everything else. Move the board branch above that one, or drop the branch while
"simplifying" the handler, and pressing + New lands on a board instead: there would be no way to
start a proposal at all, from anywhere in the app.

The `?d=` case is deliberate and predates this change: an old draft link left in browser history
lands on a board rather than a half-filled intake form nobody asked for.

── WHAT CHANGED 2026-09-17: THE BARE DOMAIN SERVES BYTES, IT NO LONGER REDIRECTS ───────────────
`/` used to answer `307 -> /portal.html`. That is a whole round trip before the first byte of the
page moves, on the request every member of staff makes to open this app, and it could never be
amortised: a 307 carries no Cache-Control, so it is re-fetched every single time. `/` now serves
portal.html's own bytes, through the same static mount that serves /portal.html — so it also gets
the ETag and the 304 that the redirect could never have.

THE COST IS `location.pathname`, and it is the only thing this change can break. After the 307 the
browser's pathname was "/portal.html". Served at the root it is "/", and auth.js reads that string
three times: `const path` at the top of its IIFE, the DENIED_PAGES permission lookup, and the
sidebar's `endsWith(href)` active-row test. The third fails SILENTLY — no error, no blank page, just
a menu that never shows which page you are on.

portal.html closes it with frontend/js/root-path.js, loaded ahead of auth.js. The tests below
EXECUTE that file rather than grepping for it (see js/root-pathname-harness.js) and assert the
consequence auth.js actually cares about, including against the pathname it would have read with
the guard removed — because "the guard is present" and "the guard works" are different claims and
only one of them is worth a test.

IT IS A FILE AND NOT AN INLINE <script> BECAUSE THE CSP FORBIDS ONE. The first version of this
change put the two lines straight in portal.html's <head>, which is where they belong on every
ground except the one that matters: a CSP violation is not a build error, it is a tag the browser
declines to run, so the guard would simply never have executed in production and the sidebar bug it
exists to prevent would have shipped with a passing test suite above it.
test_frontend_js_parses.py::test_no_frontend_js_uses_an_inline_script_or_handler is what caught it.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
AUTH_JS = (FRONTEND / "auth.js").read_text(encoding="utf-8")
PORTAL_HTML = FRONTEND / "portal.html"
ROOT_PATH_JS = FRONTEND / "js" / "root-path.js"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "root-pathname-harness.js"

HOME = "/portal.html"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def _get(url: str):
    return client.get(url, follow_redirects=False)


@pytest.fixture(scope="module")
def guard():
    """Run frontend/js/root-path.js over a set of starting URLs, in node."""
    proc = subprocess.run(["node", str(HARNESS), str(ROOT_PATH_JS), str(PORTAL_HTML)],
                          capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    return {c["from"]: c for c in out["cases"]}, out["loadOrder"]


# ── the bare domain ──────────────────────────────────────────────────────────
def test_the_bare_domain_serves_the_board_itself():
    """The ask, in one assertion — and now without the round trip that used to precede it."""
    r = _get("/")
    assert r.status_code == 200, (
        "the bare domain answered %s; it is supposed to serve the board's bytes" % r.status_code)
    assert r.content == PORTAL_HTML.read_bytes(), (
        "/ served something other than portal.html (%d bytes vs %d)"
        % (len(r.content), PORTAL_HTML.stat().st_size))


def test_the_bare_domain_no_longer_costs_a_redirect():
    """THE POINT OF THE CHANGE, stated as the thing that must not come back. A 3xx here is a
    full round trip before any HTML is sent, on every visit, uncacheable."""
    assert _get("/").status_code not in (301, 302, 303, 307, 308), (
        "/ is redirecting again — the round trip is back")


def test_the_bare_domain_and_the_page_itself_are_the_same_document():
    """Two URLs for one page is only safe while they cannot drift. They are the same file read
    through the same mount, and this says so out loud."""
    assert _get("/").content == _get(HOME).content


def test_the_bare_domain_can_be_revalidated_instead_of_re_sent():
    """The half a redirect could never have given us. `/` goes through NoCacheStaticFiles, so a
    browser that already holds the page sends If-None-Match and gets 304 + no body — where
    before it sent a request, got a 307, and then sent a second request."""
    first = _get("/")
    etag = first.headers.get("etag")
    assert etag, "/ carries no ETag, so the browser has nothing to revalidate with"
    second = client.get("/", headers={"If-None-Match": etag}, follow_redirects=False)
    assert second.status_code == 304, (
        "/ re-sent a full %s to a conditional request" % second.status_code)
    assert second.content == b""
    assert "no-cache" in (first.headers.get("cache-control") or "").lower(), (
        "/ is served with %r; it must match the policy /portal.html is served with"
        % first.headers.get("cache-control"))


def test_an_old_draft_link_in_history_lands_on_a_board_not_a_half_filled_form():
    """Predates this change and still holds: `?d=<uuid>` is what the intake form used to leave in
    history, and resuming it from the bare root shows a form for a project nobody chose."""
    r = _get("/?d=00000000-0000-0000-0000-000000000000")
    assert r.status_code == 200
    assert r.content == PORTAL_HTML.read_bytes()


def test_an_unknown_query_string_does_not_open_the_intake_form():
    """The branch is an allow-list of two, not a catch-all. `?utm_source=…` on a shared link must
    not open a blank New Project screen."""
    r = _get("/?utm_source=email&ref=slack")
    assert r.status_code == 200
    assert r.content == PORTAL_HTML.read_bytes()


# ── the branch that must survive ─────────────────────────────────────────────
def test_starting_a_new_proposal_still_reaches_the_intake_form():
    """THE one that matters. `/?new=1` is what both the Proposals Database and the board's + New
    button navigate to. If this serves the board, nothing in the app can start a bid."""
    r = _get("/?new=1")
    assert r.status_code == 200
    assert r.content == (FRONTEND / "index.html").read_bytes(), (
        "/?new=1 served the board instead of the intake form — pressing + New goes nowhere")


def test_editing_still_reaches_the_intake_form():
    r = _get("/?edit=1")
    assert r.status_code == 200
    assert r.content == (FRONTEND / "index.html").read_bytes()


def test_the_intake_form_is_served_uncached():
    """It carries a draft id in the URL and reads localStorage on boot; a cached copy is how a
    stale project appeared under a new one's id."""
    r = _get("/?new=1")
    cache = (r.headers.get("cache-control") or "").lower()
    assert "no-store" in cache, "the intake form is cacheable: %r" % cache


def test_the_new_branch_is_checked_BEFORE_the_board_is_served():
    """Asserted against the source as well as the behaviour, because the ordering is the whole
    mechanism and a reordered handler would fail every test above at once — this one says why."""
    import inspect
    src = inspect.getsource(main._root)
    assert src.index('"new" in q') < src.index("get_response"), (
        "the board is served before the ?new branch, so + New can never open the intake form")


# ── the pathname guard, executed ─────────────────────────────────────────────
@needs_node
def test_the_guard_leaves_the_pathname_the_redirect_used_to_leave(guard):
    """THE LOAD-BEARING ONE. Every auth.js read of `location.pathname` has to see the exact
    string it saw when a 307 got you here, or serving at the root is a silent behaviour change
    in the permission lookup and the sidebar."""
    cases, _ = guard
    for start in ("/", "/?utm_source=email", "/?d=00000000-0000-0000-0000-000000000000"):
        assert cases[start]["pathname"] == HOME, (
            "%s leaves pathname %r" % (start, cases[start]["pathname"]))


@needs_node
def test_without_the_guard_the_sidebar_would_stop_highlighting_the_board(guard):
    """The counterexample, and the reason the guard is not optional. `sidebarActiveWithoutGuard`
    runs auth.js:221's own `pathname.endsWith(href)` against the pathname the server now hands
    over. It is False at the root — so the Active Projects row would quietly stop lighting up,
    with nothing on screen to say why."""
    cases, _ = guard
    assert cases["/"]["sidebarActiveWithoutGuard"] is False, (
        "'/' already ends with /portal.html, so this file proves nothing about the guard")
    assert cases["/"]["sidebarActive"] is True, (
        "the guard ran and the sidebar still does not consider the board active")


@needs_node
def test_the_query_string_is_dropped_exactly_as_the_redirect_dropped_it(guard):
    """NOT tidiness — `shared.js` adopts a `?d=` it finds in the URL. A 307 to "/portal.html"
    carried no query, so preserving one here would reopen whatever draft was in somebody's
    history under whatever they did next. The hash is kept, because a 307 keeps that."""
    cases, _ = guard
    assert cases["/?d=00000000-0000-0000-0000-000000000000"]["search"] == ""
    assert cases["/?utm_source=email"]["search"] == ""
    assert cases["/#drawer"]["hash"] == "#drawer"


@needs_node
def test_the_guard_does_nothing_on_every_other_way_of_arriving(guard):
    """It fires on "/" and nowhere else. `/portal.html?open=<id>` is a real link the drawer
    sends — portal.js reads that query — and rewriting the URL there would drop it."""
    cases, _ = guard
    for start in ("/portal.html", "/portal.html?open=abc", "/projects.html"):
        assert cases[start]["replaced"] == [], (
            "the guard rewrote the URL on %s: %r" % (start, cases[start]["replaced"]))
    assert cases["/portal.html?open=abc"]["search"] == "?open=abc"
    assert cases["/projects.html"]["pathname"] == "/projects.html"


@needs_node
def test_the_guard_runs_before_anything_that_reads_the_pathname(guard):
    """Order is the mechanism, and classic <script src> tags execute in document order.
    auth.js captures `location.pathname` into a const the moment it runs, so a guard loaded
    after it would rewrite the address bar and change nothing — silently, since both files
    would still be there and still parse."""
    _, load_order = guard
    assert "/js/root-path.js" in load_order, (
        "portal.html does not load the pathname guard at all: %r" % (load_order,))
    assert "/auth.js" in load_order, "portal.html stopped loading auth.js — read this file again"
    assert load_order.index("/js/root-path.js") < load_order.index("/auth.js"), (
        "the guard is loaded after auth.js (%r), so auth.js has already read location.pathname"
        % (load_order,))


def test_the_guard_is_not_an_inline_script():
    """THE RULE THAT CAUGHT THIS, restated where somebody moving the guard back into the page
    will meet it. The CSP forbids inline script; a violating tag is not a build error, it is a
    tag the browser declines to run. The guard would be present, correct, and never executed.
    test_frontend_js_parses.py enforces this across every page — this assertion is here so the
    failure names the guard rather than "portal.html"."""
    html = PORTAL_HTML.read_text(encoding="utf-8")
    for chunk in html.split("<script")[1:]:
        head, _, rest = chunk.partition(">")
        assert "src=" in head or not rest.strip()[:200].strip(), (
            "portal.html has an inline <script> again — the CSP will not run it")
    assert ROOT_PATH_JS.exists(), "the guard file is gone; the bare domain now lies about its path"


def test_auth_js_still_reads_the_pathname_in_the_three_places_the_guard_exists_for():
    """If these ever stop existing, the guard becomes dead weight and its comment becomes a lie.
    Asserted so that removing them is a decision rather than an accident."""
    assert AUTH_JS.count("location.pathname") >= 3, (
        "auth.js reads location.pathname %d times; the guard's rationale names three"
        % AUTH_JS.count("location.pathname"))
    assert "const path = location.pathname.toLowerCase();" in AUTH_JS
    assert "DENIED_PAGES[location.pathname]" in AUTH_JS
    assert "location.pathname.toLowerCase().endsWith(href.toLowerCase())" in AUTH_JS


# ── the other half of the decision ───────────────────────────────────────────
def test_signing_in_lands_on_the_same_page_the_bare_domain_does():
    """auth.js's HOME_PAGE is used twice: `location.replace(HOME_PAGE)` when the login page finds an
    existing session, and `redirectTo` on the OAuth round trip. Both have to agree with what the
    server serves at the root, or the app opens somewhere different depending on how you arrived."""
    m = re.search(r'const HOME_PAGE = "([^"]+)"', AUTH_JS)
    assert m, "HOME_PAGE is gone from auth.js — this test needs rewriting, not deleting"
    assert m.group(1) == HOME, (
        "signing in lands on %s while the bare domain serves %s" % (m.group(1), HOME))


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
