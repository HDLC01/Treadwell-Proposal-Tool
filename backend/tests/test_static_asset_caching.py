"""What the browser re-downloads on every page load, and why it is allowed to stop.

Every page in this app boots the same handful of our own files — /js/icons.js, /auth.js,
/shared.js, /styles.css, 211 KB raw and ~69 KB gzipped — before it loads a line of its own code.
Until 2026-09-16 the static mount answered all of them with `Cache-Control: no-store` AND an
`is_not_modified()` override that returned False unconditionally. The second half is the one that
mattered: it disabled Starlette's conditional-GET short-circuit at the source, so a browser that
sent `If-None-Match` got the whole file back anyway. Four wizard steps, four full re-transfers.

THE REASON IT WAS WRITTEN THAT WAY IS REAL AND STILL HOLDS. A browser sitting on a stale done.html
missed the fetch+Blob downloader and proposals came down named after their UUID. Nobody should have
to hard-refresh after a deploy. `no-cache` keeps that promise exactly: it does not mean "do not
cache", it means "you may store this, but you must ask the origin before you reuse it, every single
time". The browser still comes to us for every file on every load. Only the ANSWER changes when
nothing moved — 304 with no body instead of the file again.

So this module asserts a pair, and the halves catch different mutations:

  * the header says `no-cache`               — caught by reverting the Cache-Control string
  * a conditional GET really gets a 304      — caught by re-adding the `is_not_modified` override,
                                               which leaves every header above still correct

and then, separately, that a file which HAS changed is served in full on the very next request —
the stale-done.html guarantee itself, executed rather than argued. That last one runs the real
NoCacheStaticFiles class over a scratch directory, because proving it needs a file we are allowed
to rewrite mid-test and frontend/ is not that.

All of it goes through TestClient against the real app. A source assertion here would be worthless:
`is_not_modified` could be reinstated by an override on a subclass, by a Starlette upgrade, or by
the mount losing this class entirely, and grepping main.py would notice none of it.
"""
import os
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

# The shared boot chain (every page loads these), plus a page and the stylesheet. done.html is
# named on purpose: it is the file whose staleness caused the bug the no-store was reached for.
BOOT_ASSETS = ["/js/icons.js", "/auth.js", "/shared.js", "/styles.css", "/done.html"]


@pytest.mark.parametrize("asset", BOOT_ASSETS)
def test_a_static_asset_is_revalidated_not_re_stored(asset):
    """`no-cache` = "store it, but ask me before every reuse". `no-store` = "never keep it", which
    is what made the 304 below impossible: there was no stored copy to validate."""
    r = client.get(asset)
    assert r.status_code == 200, "%s is not being served at all (%s)" % (asset, r.status_code)
    cache = (r.headers.get("cache-control") or "").lower()
    assert "no-cache" in cache, "%s is served with %r" % (asset, cache)
    assert "no-store" not in cache, (
        "%s is back on no-store, so the browser keeps no copy to revalidate and every load is a "
        "full re-download: %r" % (asset, cache))
    assert r.headers.get("etag"), (
        "%s carries no ETag, so the browser has nothing to send back in If-None-Match" % asset)


@pytest.mark.parametrize("asset", BOOT_ASSETS)
def test_an_unchanged_asset_comes_back_304_with_no_body(asset):
    """THE LOAD-BEARING ONE. Every header assertion above still passes with the old
    `is_not_modified(): return False` override in place — the browser would dutifully send
    If-None-Match and we would ship the whole file regardless. This is the assertion that can tell
    the difference, and it is why the override is gone rather than merely unused."""
    first = client.get(asset)
    etag = first.headers["etag"]

    second = client.get(asset, headers={"If-None-Match": etag})
    assert second.status_code == 304, (
        "%s re-sent a full %s to a conditional request — the If-None-Match short-circuit is "
        "disabled again" % (asset, second.status_code))
    assert second.content == b"", (
        "%s returned a %d-byte body with its 304; the whole saving is that there is no body"
        % (asset, len(second.content)))
    assert "no-cache" in (second.headers.get("cache-control") or "").lower(), (
        "the 304 for %s does not repeat the policy, so the browser is free to stop revalidating"
        % asset)


@pytest.mark.parametrize("asset", BOOT_ASSETS)
def test_the_http_1_0_headers_that_only_defeat_the_304_are_gone(asset):
    """`Pragma` has no defined meaning in a response (RFC 9111 makes it a request directive) and
    `Expires` is ignored whenever Cache-Control is present — so to anything modern they say nothing,
    and to an HTTP/1.0-era cache `Expires: 0` reads "never reuse this", which is the one effect they
    could still have and the exact opposite of what this mount now wants."""
    r = client.get(asset)
    assert "pragma" not in {k.lower() for k in r.headers}, "%s still sends Pragma" % asset
    assert "expires" not in {k.lower() for k in r.headers}, "%s still sends Expires" % asset


def test_the_frontend_is_actually_mounted_through_this_class():
    """The parametrized tests above would pass just as happily if the mount fell back to a plain
    StaticFiles that Starlette gave sensible defaults to. Name the class, so that swapping it out
    is a failure here rather than a silent change of policy on 23 pages."""
    mounts = [r for r in main.app.routes if getattr(r, "name", None) == "frontend"]
    assert mounts, "the frontend is not mounted — every page in the app is a 404"
    assert isinstance(mounts[0].app, main.NoCacheStaticFiles), (
        "the frontend mount is a %s, not NoCacheStaticFiles" % type(mounts[0].app).__name__)


# ── the stale-done.html guarantee, executed ──────────────────────────────────
def test_a_file_that_changed_is_sent_in_full_on_the_very_next_request(tmp_path):
    """THE WHOLE POINT OF THE NO-STORE THIS REPLACED. If `no-cache` could leave a browser on an old
    done.html, this change would be a regression that costs money — the estimator would download a
    proposal named after its UUID again and not know why.

    It cannot, and here is that claim executed rather than argued. Starlette's ETag is
    md5(st_mtime-st_size); a deploy (`git pull` + `docker compose up -d --build`) rewrites the mtime
    of every file it changes, so the validator the browser holds stops matching and it is sent the
    new bytes. Run over a scratch directory because proving it needs a file we may rewrite mid-test,
    and frontend/ is read by other modules in this suite at the same moment.

    The real NoCacheStaticFiles is mounted here, not a copy of its behaviour."""
    (tmp_path / "done.html").write_bytes(b"<p>old</p>")
    os.utime(tmp_path / "done.html", (1_700_000_000, 1_700_000_000))

    app = FastAPI()
    app.mount("/", main.NoCacheStaticFiles(directory=str(tmp_path), html=True), name="frontend")
    c = TestClient(app)

    first = c.get("/done.html")
    assert first.status_code == 200 and first.content == b"<p>old</p>"
    etag = first.headers["etag"]

    # Unchanged: the browser's copy is still good, and we say so cheaply.
    assert c.get("/done.html", headers={"If-None-Match": etag}).status_code == 304

    # Deployed: new content, new mtime — exactly what git pull + docker build leave behind.
    (tmp_path / "done.html").write_bytes(b"<p>the new downloader</p>")
    os.utime(tmp_path / "done.html", (1_700_000_900, 1_700_000_900))

    after = c.get("/done.html", headers={"If-None-Match": etag})
    assert after.status_code == 200, (
        "a deployed change was answered with %s — the browser would keep serving the stale page, "
        "which is the bug no-store was reached for" % after.status_code)
    assert after.content == b"<p>the new downloader</p>"
    assert after.headers["etag"] != etag, "the validator did not move with the file"


def test_the_scratch_mount_above_would_notice_a_cache_that_never_expired(tmp_path):
    """The counterexample for the test above, which would otherwise be the cheap kind of green:
    it has to be capable of FAILING when a stale copy is served. Serve the same bytes at the same
    mtime and the 304 must still come back — so the 200 asserted above is a response to the change,
    not something this mount does unconditionally."""
    (tmp_path / "a.html").write_bytes(b"<p>x</p>")
    os.utime(tmp_path / "a.html", (1_700_000_000, 1_700_000_000))

    app = FastAPI()
    app.mount("/", main.NoCacheStaticFiles(directory=str(tmp_path), html=True), name="frontend")
    c = TestClient(app)

    etag = c.get("/a.html").headers["etag"]
    # Rewritten with identical bytes and mtime restored: nothing a validator can see moved.
    (tmp_path / "a.html").write_bytes(b"<p>x</p>")
    os.utime(tmp_path / "a.html", (1_700_000_000, 1_700_000_000))
    assert c.get("/a.html", headers={"If-None-Match": etag}).status_code == 304, (
        "this mount answers 200 no matter what, so the previous test proves nothing")


def test_the_assets_under_test_are_the_ones_the_pages_load():
    """A list of asset paths in a test file is exactly the kind of thing that outlives the files it
    names. Tie it to the HTML: each one has to be referenced by a real page, or this module is
    measuring the cache policy on files nobody downloads."""
    frontend = pathlib.Path(main.FRONTEND_DIR)
    pages = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                      for p in frontend.glob("*.html"))
    for asset in BOOT_ASSETS:
        if asset.endswith(".html"):
            assert (frontend / asset.lstrip("/")).exists(), "%s no longer exists" % asset
            continue
        assert '"%s"' % asset in pages, "no page loads %s any more" % asset
