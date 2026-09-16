"""The /api/proposal-template block cache, and what makes it safe.

Rebuilding the block list re-parses the .docx and walks every paragraph — ~105 ms
of CPU per request, paid even on a 304 that then sent no body. The blocks only
change when the template file changes, so they are cached.

THE INVALIDATION IS THE WHOLE RISK, not the speed. A block `id` is an index into
`proposal_writer.iter_editable_blocks`'s walk, and `_apply_paragraph_overrides`
resolves an estimator's saved override back onto the template BY THAT INDEX. Serve
blocks from a template the file no longer matches and their edits land on the wrong
paragraphs or vanish — on a document a customer reads. So the cache key has to bust
on exactly what the ETag busts on, and these tests are mostly about proving it does.

Everything here drives a COPY of a real template through a repointed
`pick_template`, so the invalidation runs on the genuine mechanism (the file's own
`st_mtime_ns`), not on a stubbed version token that could agree with itself.
"""
import io
import os
import zipfile

import docx
import pytest
from fastapi.testclient import TestClient

import main
import proposal_writer as pw

client = TestClient(main.app)

# Captured before any test can monkeypatch it: the invalidation tests repoint
# `pick_template` at a temp copy and still need the REAL one to fetch a second,
# genuinely different template to overwrite that copy with.
_REAL_PICK = pw.pick_template


@pytest.fixture(autouse=True)
def _clear_template_cache():
    """The cache is module-level and outlives a test. Clear it around each one so a
    body built from one test's temp template can never answer another's request."""
    main._PROPOSAL_TEMPLATE_CACHE.clear()
    yield
    main._PROPOSAL_TEMPLATE_CACHE.clear()


def _get(work_type="epoxy", audience="Direct", inm=None):
    headers = {} if inm is None else {"If-None-Match": inm}
    return client.get(
        "/api/proposal-template?work_type=%s&audience=%s" % (work_type, audience),
        headers=headers)


def _copy_template(tmp_path, work_type="epoxy", audience="Direct", name="t.docx"):
    dst = tmp_path / name
    dst.write_bytes(pw.pick_template(work_type, audience).read_bytes())
    return dst


def _repoint(monkeypatch, path):
    monkeypatch.setattr(pw, "pick_template", lambda wt, aud: path)


def _bump_mtime(path):
    """Force a NEW st_mtime_ns. Two writes inside one filesystem tick can share a
    timestamp, which would let this suite pass without ever testing invalidation."""
    before = os.stat(str(path)).st_mtime_ns
    os.utime(str(path), ns=(before + 10 ** 9, before + 10 ** 9))
    after = os.stat(str(path)).st_mtime_ns
    assert after != before, "mtime did not move; the invalidation test would be vacuous"
    return after


# ── the cache serves what a fresh build would have ───────────────────────────
def test_a_cache_hit_is_byte_identical_to_the_build_that_filled_it():
    first = _get()
    assert first.status_code == 200
    assert len(main._PROPOSAL_TEMPLATE_CACHE) == 1, "nothing was cached"
    second = _get()
    assert second.content == first.content
    assert second.headers["etag"] == first.headers["etag"]
    assert second.headers["content-type"] == first.headers["content-type"]
    assert second.headers["cache-control"] == first.headers["cache-control"]

    # and a hit really was a hit — not a silent rebuild that happened to agree
    main._PROPOSAL_TEMPLATE_CACHE.clear()
    rebuilt = _get()
    assert rebuilt.content == first.content


def test_the_payload_still_carries_the_template_version_its_etag_was_cut_from():
    """`template_version` is what the frontend compares against a cached id set.
    If the body's copy could disagree with the ETag the response was tagged with,
    a stale id set would look fresh."""
    r = _get()
    tver = r.json()["template_version"]
    expected = main._etag_of("epoxy:Direct:%s:s%s" % (tver, main._BLOCK_SCHEMA_VERSION))
    assert r.headers["etag"] == expected


# ── invalidation: the part that protects an estimator's edits ────────────────
def test_a_rewritten_template_busts_both_the_cache_and_the_etag(tmp_path, monkeypatch):
    """Re-annotating a .docx changes its mtime. If the cache outlived that, the
    editor would keep handing out ids from the OLD paragraph walk."""
    tpl = _copy_template(tmp_path)
    _repoint(monkeypatch, tpl)

    old = _get()
    old_blocks = old.json()["blocks"]
    old_etag = old.headers["etag"]

    # A genuinely different document (Direct Polish over Direct Epoxy) so a stale
    # body is detectable by its CONTENT, not only by a version string.
    tpl.write_bytes(_REAL_PICK("polish", "Direct").read_bytes())
    _bump_mtime(tpl)

    new = _get()
    assert new.status_code == 200
    assert new.headers["etag"] != old_etag, "the ETag did not move"
    new_blocks = new.json()["blocks"]
    assert [b["text"] for b in new_blocks] != [b["text"] for b in old_blocks], \
        "the cache served the OLD template's blocks after the file changed"


def test_an_etag_from_the_old_template_gets_the_new_document_not_a_304(tmp_path, monkeypatch):
    """The revalidation shortcut returns 304 before it looks at anything. It must
    key on the current file, or a browser holding yesterday's tag is told its stale
    id set is still good."""
    tpl = _copy_template(tmp_path)
    _repoint(monkeypatch, tpl)

    old = _get()
    stale_etag = old.headers["etag"]
    assert _get(inm=stale_etag).status_code == 304        # unchanged file: 304 is right

    tpl.write_bytes(_REAL_PICK("polish", "Direct").read_bytes())
    _bump_mtime(tpl)

    after = _get(inm=stale_etag)
    assert after.status_code == 200, "a stale ETag was answered 304 against a CHANGED template"
    assert after.json()["blocks"], "the 200 came back without blocks"


def test_bumping_the_block_schema_version_busts_the_cache(monkeypatch):
    """`_BLOCK_SCHEMA_VERSION` exists because the block SHAPE can change without the
    .docx changing. The cache has to honour it for the same reason the ETag does."""
    first = _get()
    assert len(main._PROPOSAL_TEMPLATE_CACHE) == 1
    monkeypatch.setattr(main, "_BLOCK_SCHEMA_VERSION", "999-test")
    second = _get()
    assert second.headers["etag"] != first.headers["etag"]
    assert len(main._PROPOSAL_TEMPLATE_CACHE) == 2, "the bumped schema reused the old entry"
    assert _get(inm=first.headers["etag"]).status_code == 200


def test_two_work_types_never_share_a_cache_entry():
    epoxy = _get("epoxy", "Direct").json()
    polish = _get("polish", "Direct").json()
    assert epoxy["template_name"] != polish["template_name"]
    assert epoxy["work_type"] == "epoxy" and polish["work_type"] == "polish"
    assert [b["text"] for b in epoxy["blocks"]] != [b["text"] for b in polish["blocks"]]


def test_work_types_that_resolve_to_one_file_still_echo_their_own(monkeypatch):
    """combo/GC and epoxy/GC are the SAME .docx. The bodies differ anyway (each
    echoes its own work_type), so a cache keyed only on the file would serve one
    caller the other's payload."""
    assert pw.pick_template("combo", "GC") == pw.pick_template("epoxy", "GC")
    combo = _get("combo", "GC").json()
    epoxy = _get("epoxy", "GC").json()
    assert combo["work_type"] == "combo"
    assert epoxy["work_type"] == "epoxy"
    assert combo["template_name"] == epoxy["template_name"]


def test_the_served_ids_still_land_on_the_template_walk():
    """The contract `_apply_paragraph_overrides` depends on: block id N is the Nth
    entry of `iter_editable_blocks`. Checked against a CACHED response, because a
    cache is exactly where this could silently stop being true."""
    _get()                                   # fill the cache
    served = _get().json()["blocks"]         # ...and read it back out of the cache
    d = docx.Document(str(pw.pick_template("epoxy", "Direct")))
    pw._normalize_work_label_formatting(d)
    walk = [(idx, text) for idx, _k, _p, _ib, text, _t in pw.iter_editable_blocks(d)]
    assert len(served) == len(walk)
    assert [(b["id"], b["text"]) for b in served] == walk


def test_a_revalidation_never_opens_the_template(monkeypatch):
    """The 304 used to re-parse the .docx and rebuild all ~172 blocks before
    sending no body. Proven by making the parse fatal."""
    etag = _get().headers["etag"]
    main._PROPOSAL_TEMPLATE_CACHE.clear()

    def boom(*a, **k):
        raise AssertionError("a revalidation opened the template")

    monkeypatch.setattr(main.docx, "Document", boom)
    r = _get(inm=etag)
    assert r.status_code == 304
    assert r.content == b""
    assert r.headers["etag"] == etag


def test_etag_of_agrees_with_versioned_json():
    """Two places now turn a version string into a tag. If they drifted, a browser
    would revalidate against a tag this endpoint never issues and 304 would stop
    working (or worse, start working by accident)."""
    class _Req:
        headers = {}

    for version in ("epoxy:Direct:123:s7", "", "a:b:c", "unicode-\u00e9"):
        assert main._etag_of(version) == main._versioned_json(
            _Req(), {"x": 1}, version=version).headers["etag"]


def test_the_cache_cannot_grow_without_bound():
    """`work_type` is a query string and `pick_template` FALLS BACK rather than
    raising, so every unmapped spelling mints a full ~106 KB body."""
    cap = main._PROPOSAL_TEMPLATE_CACHE.maxsize
    assert cap <= 64, (
        "the cache holds ~106 KB per entry and only 11 (work_type, audience) pairs are "
        "real; a cap this large is not a bound")
    for i in range(cap * 3):
        assert _get("junk%d" % i, "Direct").status_code == 200
    assert len(main._PROPOSAL_TEMPLATE_CACHE) <= cap


def test_concurrent_loads_all_get_the_same_body():
    """FastAPI runs a sync endpoint in a threadpool, so two Proposal Review loads
    really can land on the cache at once — and cachetools caches are documented as
    NOT thread-safe, which is why the dict bookkeeping is under a lock.

    A race is not deterministic, so treat this as a smoke test rather than a proof:
    it catches a gross error (an exception, or two callers handed different bodies),
    not every interleaving."""
    import threading

    results = []
    errors = []

    def hit(wt):
        try:
            r = _get(wt, "Direct")
            results.append((wt, r.status_code, r.content))
        except Exception as exc:          # noqa: BLE001 - the point is to see it
            errors.append(exc)

    threads = [threading.Thread(target=hit, args=(wt,))
               for wt in ("epoxy", "polish", "epoxy", "combo", "polish",
                          "epoxy", "combo", "polish")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, errors
    assert len(results) == len(threads)
    assert all(s == 200 for _wt, s, _b in results)
    by_type = {}
    for wt, _s, body in results:
        by_type.setdefault(wt, set()).add(body)
    for wt, bodies in by_type.items():
        assert len(bodies) == 1, "%s got %d different bodies" % (wt, len(bodies))
    assert len(by_type) == 3


# ── /api/proposal-template/media ─────────────────────────────────────────────
def _media(name, work_type="epoxy", audience="Direct", inm=None):
    headers = {} if inm is None else {"If-None-Match": inm}
    return client.get(
        "/api/proposal-template/media?work_type=%s&audience=%s&name=%s"
        % (work_type, audience, name), headers=headers)


def test_a_media_revalidation_never_opens_the_zip(monkeypatch):
    """It used to inflate a ~90 KB PNG out of the package and then throw it away."""
    first = _media("image1.png")
    assert first.status_code == 200 and len(first.content) > 1000

    def boom(*a, **k):
        raise AssertionError("a media revalidation opened the template package")

    monkeypatch.setattr(zipfile, "ZipFile", boom)
    r = _media("image1.png", inm=first.headers["etag"])
    assert r.status_code == 304
    assert r.content == b""
    assert r.headers["etag"] == first.headers["etag"]


def test_an_unknown_media_name_is_still_404_with_an_if_none_match():
    """Checking the tag first must not turn a miss into a 304 — the name is inside
    the tag, so no client can be holding one for a part that was never served."""
    real = _media("image1.png").headers["etag"]
    assert _media("nope.png", inm=real).status_code == 404
    assert _media("nope.png", inm='W/"deadbeefdeadbeef"').status_code == 404
    assert _media("nope.png").status_code == 404


def test_a_media_etag_is_per_name_and_per_template():
    one = _media("image1.png").headers["etag"]
    two = _media("image2.png").headers["etag"]
    gc = _media("image1.png", audience="GC").headers["etag"]
    assert one != two
    assert one != gc
    # ...and a tag for the WRONG image does not unlock a 304
    assert _media("image1.png", inm=two).status_code == 200


def test_media_bytes_are_unchanged_and_still_come_from_the_package():
    r = _media("image1.png")
    with zipfile.ZipFile(io.BytesIO(pw.pick_template("epoxy", "Direct").read_bytes())) as z:
        assert r.content == z.read("word/media/image1.png")
    assert r.headers["content-type"] == "image/png"

