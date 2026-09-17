"""The one resource hint in this frontend, and the rule for where it belongs.

Every page in the app pulls supabase-js off cdn.jsdelivr.net, and estimate-review.html and
info-sheet.html pull HyperFormula off it too. On most pages that <script> sits at the BOTTOM of the
body, so the browser does not learn the origin exists until it has parsed the whole document — and
only then starts DNS, TCP and TLS to a host it has never contacted. `preconnect` moves that
handshake to the top of the <head>, where it overlaps the rest of the page load instead of blocking
the end of it. No bytes are fetched; it is a connection, not a download.

THE `crossorigin` ATTRIBUTE IS NOT DECORATION. Those script tags carry `crossorigin="anonymous"`
(they are SRI-pinned with `integrity=`), so the browser fetches them in CORS mode. A preconnect
WITHOUT `crossorigin` warms a connection in the other mode, the script cannot use it, and a second
handshake happens anyway — the hint costs a socket and saves nothing. This is the single easiest way
for this change to become decorative, so it is asserted per page.

WHAT THIS DELIBERATELY IS NOT. Not `preload`, which would download the library on pages whose real
cost is elsewhere. Not `dns-prefetch`, which resolves the name and stops short of the TLS handshake
that is most of the latency. Not a hint on pages that do not use the origin: an unused preconnect
holds a socket open for ~10s for nothing, so the negative half below is a real assertion, not
symmetry for its own sake.
"""
import pathlib
import re

import pytest

import main

FRONTEND = pathlib.Path(main.FRONTEND_DIR)
HINT = '<link rel="preconnect" href="https://cdn.jsdelivr.net" crossorigin'

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
# The hint's own comment names the CDN, so the scan for "does this page USE the origin" has to read
# past comments — otherwise adding the hint is what makes a page look like it needs the hint.
_CDN_SCRIPT = re.compile(r'<script[^>]*src="https://cdn\.jsdelivr\.net/', re.I)


def _pages():
    return sorted(FRONTEND.glob("*.html"))


def _code(page: pathlib.Path) -> str:
    return _HTML_COMMENT.sub("", page.read_text(encoding="utf-8", errors="replace"))


USERS = [p for p in _pages() if _CDN_SCRIPT.search(_code(p))]
NON_USERS = [p for p in _pages() if not _CDN_SCRIPT.search(_code(p))]


def test_the_two_lists_are_both_populated():
    """Read this first: both parametrized tests below are vacuous if their list is empty, and an
    empty list is exactly what a broken `_CDN_SCRIPT` regex produces. 23 of the 24 pages load
    supabase-js; dropbox.html is a meta-refresh stub that loads nothing."""
    assert len(USERS) >= 20, "only %d pages look like CDN users: %r" % (len(USERS), USERS)
    assert NON_USERS, (
        "no page in the frontend is free of the CDN, so the 'absent where unused' test below can "
        "never fail and proves nothing")


@pytest.mark.parametrize("page", USERS, ids=lambda p: p.name)
def test_every_page_that_uses_the_cdn_warms_the_connection(page):
    html = page.read_text(encoding="utf-8", errors="replace")
    assert HINT in html, (
        "%s loads a script off cdn.jsdelivr.net but never tells the browser about the origin until "
        "the parser reaches that tag" % page.name)


@pytest.mark.parametrize("page", USERS, ids=lambda p: p.name)
def test_the_hint_is_in_the_head_and_ahead_of_the_script_it_is_for(page):
    """A preconnect below the tag it warms is a no-op — the connection is already opening. A
    preconnect in the <body> is worse than a no-op: the browser's preload scanner has already gone
    past it."""
    html = page.read_text(encoding="utf-8", errors="replace")
    head_end = html.index("</head>")
    assert html.index(HINT) < head_end, "%s puts the hint outside its <head>" % page.name
    first_script = _CDN_SCRIPT.search(_HTML_COMMENT.sub("", html))
    assert first_script, page.name
    assert html.index(HINT) < html.index(first_script.group(0)), (
        "%s declares the hint after the script it is supposed to warm" % page.name)


@pytest.mark.parametrize("page", NON_USERS, ids=lambda p: p.name)
def test_a_page_that_does_not_use_the_cdn_does_not_open_a_connection_to_it(page):
    """An unused preconnect is not free: the browser holds the socket open for ~10 seconds waiting
    for a request that never comes, and on a phone that is radio time."""
    assert "preconnect" not in page.read_text(encoding="utf-8", errors="replace"), (
        "%s warms cdn.jsdelivr.net but loads nothing from it" % page.name)


def test_nothing_was_preloaded_or_self_hosted_along_the_way():
    """jsdelivr already serves these two libraries `immutable` with a year-long max-age, so a
    repeat visitor pays nothing for them at all. `preload` would make this app download them again
    on pages that only need the connection warm, and vendoring them under our own
    `no-cache, must-revalidate` would turn a free cache hit into a revalidation on every load. The
    hint is the whole change."""
    for page in _pages():
        html = page.read_text(encoding="utf-8", errors="replace")
        assert 'rel="preload"' not in html, "%s preloads something off a CDN" % page.name
        for lib in ("supabase-js@", "hyperformula@"):
            assert '"/%s' % lib not in html and "/js/%s" % lib not in html, (
                "%s looks like it self-hosts %s" % (page.name, lib))
