"""Preloading the one request the boot path cannot discover for itself.

Every page loads /auth.js, and auth.js cannot do anything until it has answered one question: what
are the Supabase URL and anon key? It asks by fetching /api/public-config, and it cannot ask until
it has been downloaded, parsed and run. So the browser learns that request exists one full round
trip later than it needed to, on all 23 pages, every cold load.

`preload` moves that discovery into the <head>, where the request goes out in parallel with
auth.js's own download instead of after it. Nothing else in this frontend qualifies: there are no
webfonts, no @import, no dynamic import(), and no script injected by JS -- every other resource is
a plain tag the preload scanner already finds in the first milliseconds. This one is invisible
until JS runs, which is the whole and only reason it earns a hint.

THIS DOES NOT CONTRADICT test_cdn_preconnect.py. That file rejects `preload` for the supabase-js
BUNDLE, and it is right to: the library is a static <script> tag the parser reaches on its own, so
preloading it re-announces something already known. The config request is the opposite case. Same
keyword, different resource, opposite answer.

`as="fetch"` AND `crossorigin` ARE BOTH LOAD-BEARING, which is why they are asserted per page.
fetch() defaults to CORS mode, so a preload whose mode does not match is not reused: the browser
downloads the config, throws it away, and auth.js requests it AGAIN. That failure is silent, costs
an extra request, and makes the page slower than having no hint at all -- the exact opposite of the
change. A browser check belongs on top of this, but the shape is pinned here.

THE HREF IS NOT HARDCODED AGAINST A STRING. It is checked against what auth.js actually fetches
before it constructs the Supabase client. Hardcoding would let someone rename the endpoint in
auth.js and leave 23 pages preloading a URL nothing asks for -- a wasted request on every page
load, with every test still green.
"""
import pathlib
import re

import pytest

import main

FRONTEND = pathlib.Path(main.FRONTEND_DIR)
AUTH_JS = FRONTEND / "auth.js"

_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_PRELOAD = re.compile(r'<link rel="preload" href="([^"]+)"([^>]*)>')
_AUTH_TAG = re.compile(r'<script[^>]*src="/auth\.js"')
# `fetch(apiBase() + "/api/...")` -- the form auth.js uses for every call it makes.
_AUTH_FETCH = re.compile(r'fetch\(\s*apiBase\(\)\s*\+\s*"(/api/[A-Za-z0-9\-_/]+)"')


def _pages():
    return sorted(FRONTEND.glob("*.html"))


def _code(page: pathlib.Path) -> str:
    """The page with HTML comments stripped, so the hint's own comment cannot satisfy a scan."""
    return _HTML_COMMENT.sub("", page.read_text(encoding="utf-8", errors="replace"))


def _boot_fetches() -> list:
    """Every /api path auth.js fetches BEFORE it can construct the Supabase client.

    Those are the requests that block sign-in, and so the only ones a preload in the <head> can
    usefully overlap. Anything auth.js fetches later (notifications, /api/me) happens well after
    the parser is done and gains nothing from a hint."""
    js = AUTH_JS.read_text(encoding="utf-8", errors="replace")
    cut = js.find("createClient(")
    assert cut > 0, "auth.js no longer calls createClient() -- this test's premise is gone"
    return [m.group(1) for m in _AUTH_FETCH.finditer(js[:cut])]


def _auth_pages():
    return [p for p in _pages() if _AUTH_TAG.search(_code(p))]


def test_the_pages_under_test_are_the_ones_that_load_auth_js():
    """Guard against the set going empty and every assertion below passing vacuously."""
    pages = _auth_pages()
    assert len(pages) >= 20, "expected the whole app to load auth.js, found %d" % len(pages)
    assert "index.html" in [p.name for p in pages]


def test_auth_js_still_blocks_on_a_config_fetch_before_sign_in():
    """The premise. If auth.js stops fetching config before createClient, the hint is dead weight
    and should be deleted rather than left pointing at nothing."""
    boot = _boot_fetches()
    assert boot, "auth.js fetches no /api path before createClient -- delete the preload"
    assert "/api/public-config" in boot, boot


@pytest.mark.parametrize("page", _auth_pages(), ids=lambda p: p.name)
def test_every_auth_page_preloads_what_the_boot_path_will_ask_for(page):
    """Mutation: drop the <link rel=preload> from any one page."""
    hits = _PRELOAD.findall(_code(page))
    assert hits, "%s loads auth.js but preloads nothing" % page.name
    hrefs = [h for h, _ in hits]
    boot = _boot_fetches()
    for href in hrefs:
        assert href in boot, (
            "%s preloads %r, which auth.js does not fetch before createClient. A preload nothing "
            "asks for is a wasted request on every load of this page." % (page.name, href))


@pytest.mark.parametrize("page", _auth_pages(), ids=lambda p: p.name)
def test_the_preload_is_fetch_mode_and_cors_so_the_response_is_actually_reused(page):
    """THE SILENT FAILURE. Without `as="fetch"` the browser cannot match the preload to the
    request; without `crossorigin` the CORS modes differ and it cannot either. Both cases download
    the config, discard it, and let auth.js fetch it a second time -- slower than no hint.

    Mutation: remove `crossorigin`, or change `as="fetch"` to `as="script"`, on any one page."""
    for href, attrs in _PRELOAD.findall(_code(page)):
        assert 'as="fetch"' in attrs, "%s: preload of %s is missing as=\"fetch\"" % (page.name, href)
        assert "crossorigin" in attrs, (
            "%s: preload of %s has no crossorigin, so fetch() will not reuse it and the request "
            "happens twice" % (page.name, href))


def test_a_page_without_auth_js_does_not_carry_the_hint():
    """An unused preload is a download nobody consumes. dropbox.html is the live counterexample
    that keeps the negative half honest."""
    for page in _pages():
        if _AUTH_TAG.search(_code(page)):
            continue
        assert not _PRELOAD.search(_code(page)), (
            "%s does not load auth.js but preloads the config anyway" % page.name)
