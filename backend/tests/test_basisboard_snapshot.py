"""The analytics dataset has to survive a restart, and no reader should ever build it.

Reading the whole bid history is ~45 paced requests. That work used to live only in
process memory, so every deploy threw it away and the next person to open Analytics
either waited out a cold build or looked at an empty "building…" page. The dashboard felt
slow for a reason that had nothing to do with the dashboard.

Two things fix it, and both are tested here:

  * every successful build is written to the data volume, and a fresh process restores it
    before it has fetched anything;
  * a refresher thread rebuilds on a clock, so the API sees one build per interval no
    matter how many people have the page open — and nobody's page load pays for one.

The care in these tests is mostly about what must NOT happen: a restored file must not be
mistaken for fresh data, a corrupt one must not reach the dashboard, and the refresher
must not go anywhere near an upstream that is already refusing us.
"""
import json
import threading
import time

import pytest

import basisboard_client as bb


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    """Every test gets its own empty volume and a cold module."""
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(bb, "_SNAPSHOT_FILE", tmp_path / "basisboard_analytics.json")
    monkeypatch.setattr(bb, "_snapshot_loaded", False)
    bb._analytics_cache.clear()
    bb._analytics_last_good.clear()
    bb._analytics_state.update({"building": False, "error": ""})
    bb._BREAKER.ok()
    yield
    bb._analytics_cache.clear()
    bb._analytics_last_good.clear()
    bb._BREAKER.ok()


def _dataset(n=3, **extra):
    rows = [{"id": f"p{i}", "name": f"Bid {i}", "bid_deadline_at": None} for i in range(n)]
    out = {"ok": True, "configured": True, "stale": False, "projects": rows,
           "shown": n, "total": n, "truncated": False, "stages": [], "estimators": [],
           "companies": [], "trades": [], "generated_at": "2026-08-03T12:00:00Z"}
    out.update(extra)
    return out


# ── writing ───────────────────────────────────────────────────────────
def test_a_successful_build_lands_on_disk():
    bb._save_snapshot(_dataset(4))
    payload = json.loads(bb._SNAPSHOT_FILE.read_text(encoding="utf-8"))
    assert len(payload["snapshot"]["projects"]) == 4
    assert payload["saved_at"] > 0


def test_the_write_is_atomic_so_a_reader_never_sees_half_a_file():
    """A 3,400-bid dataset is not a small write. Without tmp+replace, a restart
    mid-write would leave a truncated file that json.loads happily rejects — or
    worse, one that parses into a dataset with no rows."""
    bb._save_snapshot(_dataset(2))
    bb._save_snapshot(_dataset(9))
    assert len(bb._load_snapshot()["projects"]) == 9
    assert not list(bb._DATA_DIR.glob("*.tmp")), "a temp file was left behind"


def test_an_unwritable_volume_does_not_fail_the_build(monkeypatch):
    """Local dev and tests have no /app/data. Losing the snapshot costs one slow page
    load; raising here would throw away a dataset we just spent 45 requests on."""
    monkeypatch.setattr(bb, "_DATA_DIR", bb.Path("/nope/not/here"))
    bb._save_snapshot(_dataset())            # must not raise


def test_the_refresh_path_saves_what_it_built(monkeypatch):
    monkeypatch.setattr(bb, "_build_analytics", lambda: _dataset(5))
    bb._ANALYTICS_REFRESH_LOCK.acquire(blocking=False)
    bb._refresh_analytics()
    assert bb._SNAPSHOT_FILE.is_file()
    assert len(bb._load_snapshot()["projects"]) == 5


# ── reading ───────────────────────────────────────────────────────────
def test_no_file_reads_as_no_snapshot():
    assert bb._load_snapshot() is None


@pytest.mark.parametrize("junk", [
    "",                                  # empty — an interrupted write
    "{",                                 # truncated
    "null",                              # parses, isn't a dict
    '"a string"',                        # parses, wrong type
    '{"saved_at": 1}',                   # no snapshot key
    '{"saved_at": 1, "snapshot": 7}',    # snapshot isn't a dict
    '{"saved_at": 1, "snapshot": {}}',   # no projects list
    '{"saved_at": 1, "snapshot": {"projects": "nope"}}',
])
def test_a_garbled_file_reads_as_no_snapshot(junk):
    """Every kind of unusable has to look the same to the caller: absent. The shape
    check matters as much as the parse — a file that parsed but had no `projects`
    would reach the dashboard as a dataset with no rows, which is indistinguishable
    from "Treadwell has never bid anything"."""
    bb._SNAPSHOT_FILE.write_text(junk, encoding="utf-8")
    assert bb._load_snapshot() is None


def test_a_stale_snapshot_is_dropped_rather_than_shown(monkeypatch):
    """Old numbers are a head start for a few hours and a lie after a week. A refresh
    is always already in flight when we serve one, so dropping it costs seconds of
    empty state, once."""
    monkeypatch.setattr(bb, "_SNAPSHOT_MAX_AGE_S", 3600)
    bb._SNAPSHOT_FILE.write_text(json.dumps(
        {"saved_at": time.time() - 7200, "snapshot": _dataset()}), encoding="utf-8")
    assert bb._load_snapshot() is None


def test_a_snapshot_from_the_future_is_dropped():
    """A clock correction on the VPS would otherwise make a file immortal."""
    bb._SNAPSHOT_FILE.write_text(json.dumps(
        {"saved_at": time.time() + 86400, "snapshot": _dataset()}), encoding="utf-8")
    assert bb._load_snapshot() is None


def test_a_recent_snapshot_is_restored():
    bb._SNAPSHOT_FILE.write_text(json.dumps(
        {"saved_at": time.time() - 60, "snapshot": _dataset(6)}), encoding="utf-8")
    assert len(bb._load_snapshot()["projects"]) == 6


# ── serving it ────────────────────────────────────────────────────────
def test_a_restored_snapshot_serves_immediately_and_says_it_is_stale(monkeypatch):
    """THE point of the whole change: a brand-new process, nothing fetched, and the
    page still gets real rows on the first request.

    `stale: true` is not a detail — the cache means "fresh", and this file could have
    been written days ago if the box was down. Presenting old totals as current would
    be worse than the slow load we're fixing."""
    monkeypatch.setattr(bb, "_start_refresh", lambda: True)
    bb._SNAPSHOT_FILE.write_text(json.dumps(
        {"saved_at": time.time() - 60, "snapshot": _dataset(7)}), encoding="utf-8")

    out = bb.get_analytics()
    assert out["shown"] == 7 and len(out["projects"]) == 7
    assert out["stale"] is True
    assert not out.get("building"), "it has data — it must not report an empty build"


def test_the_restored_snapshot_never_enters_the_fresh_cache(monkeypatch):
    """If hydration wrote into the TTL cache, a week-old file would read as fresh for
    the next five minutes and no refresh would be triggered."""
    monkeypatch.setattr(bb, "_start_refresh", lambda: True)
    bb._SNAPSHOT_FILE.write_text(json.dumps(
        {"saved_at": time.time() - 60, "snapshot": _dataset()}), encoding="utf-8")
    bb.get_analytics()
    assert bb._analytics_cache.get("analytics") is None


def test_serving_a_restored_snapshot_still_kicks_off_a_refresh(monkeypatch):
    calls = []
    monkeypatch.setattr(bb, "_start_refresh", lambda: calls.append(1) or True)
    bb._SNAPSHOT_FILE.write_text(json.dumps(
        {"saved_at": time.time() - 60, "snapshot": _dataset()}), encoding="utf-8")
    bb.get_analytics()
    assert calls, "the page paints old numbers and nothing goes to fetch the new ones"


def test_disk_is_read_once_per_process_not_once_per_request(monkeypatch):
    """Analytics and the Bid Calendar both poll. Re-reading a multi-megabyte file on
    every request would trade the old slow build for a new slow read."""
    monkeypatch.setattr(bb, "_start_refresh", lambda: True)
    reads = []
    real = bb._load_snapshot
    monkeypatch.setattr(bb, "_load_snapshot", lambda: reads.append(1) or real())
    bb._SNAPSHOT_FILE.write_text(json.dumps(
        {"saved_at": time.time() - 60, "snapshot": _dataset()}), encoding="utf-8")
    for _ in range(5):
        bb.get_analytics()
    assert len(reads) == 1


@pytest.mark.parametrize("state", ["absent", "corrupt", "expired"])
def test_disk_is_read_once_even_when_there_is_nothing_usable_on_it(monkeypatch, state):
    """The case the happy-path test above cannot see.

    When a snapshot IS restored, last-good gets populated and that alone stops the
    second read. When there ISN'T one — a brand-new volume, a corrupt file, an expired
    one — last-good stays empty, so without its own guard hydration would stat and
    re-read the file on every single request, forever. That is the state a fresh
    deploy is in, which is exactly when the tool is busiest."""
    monkeypatch.setattr(bb, "_start_refresh", lambda: True)
    if state == "corrupt":
        bb._SNAPSHOT_FILE.write_text("{ truncated", encoding="utf-8")
    elif state == "expired":
        monkeypatch.setattr(bb, "_SNAPSHOT_MAX_AGE_S", 60)
        bb._SNAPSHOT_FILE.write_text(json.dumps(
            {"saved_at": time.time() - 999, "snapshot": _dataset()}), encoding="utf-8")

    reads = []
    real = bb._load_snapshot
    monkeypatch.setattr(bb, "_load_snapshot", lambda: reads.append(1) or real())
    for _ in range(5):
        bb.get_analytics()
    assert len(reads) == 1, f"the volume was read {len(reads)}x with a {state} snapshot"


def test_a_live_build_is_never_overwritten_by_an_older_file(monkeypatch):
    """Hydration races the first real build on a busy boot. The fetched dataset wins."""
    monkeypatch.setattr(bb, "_start_refresh", lambda: True)
    bb._analytics_last_good["snapshot"] = _dataset(99)
    bb._SNAPSHOT_FILE.write_text(json.dumps(
        {"saved_at": time.time() - 60, "snapshot": _dataset(1)}), encoding="utf-8")
    bb._hydrate_from_snapshot()
    assert bb._analytics_last_good["snapshot"]["shown"] == 99


def test_hydration_is_thread_safe(monkeypatch):
    """Several pages can arrive in the same instant after a restart."""
    monkeypatch.setattr(bb, "_start_refresh", lambda: True)
    bb._SNAPSHOT_FILE.write_text(json.dumps(
        {"saved_at": time.time() - 60, "snapshot": _dataset(3)}), encoding="utf-8")
    reads = []
    real = bb._load_snapshot
    monkeypatch.setattr(bb, "_load_snapshot", lambda: reads.append(1) or real())

    threads = [threading.Thread(target=bb._hydrate_from_snapshot) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert len(reads) == 1


# ── the refresher ─────────────────────────────────────────────────────
def test_the_refresher_never_starts_under_pytest():
    """A background thread reaching for Basisboard turns an offline suite into a slow
    one and fills it with network warnings."""
    assert bb.ensure_refresher_started() is False


def test_the_refresher_does_not_start_when_basisboard_is_unconfigured(monkeypatch):
    monkeypatch.delenv("BASISBOARD_API_KEY", raising=False)
    monkeypatch.setitem(__import__("sys").modules, "pytest", None)
    try:
        assert bb.ensure_refresher_started() is False
    finally:
        __import__("sys").modules["pytest"] = pytest


def test_a_refresher_tick_stays_away_from_an_open_breaker(monkeypatch):
    """The whole outage was us continuing to call an upstream that was refusing us.
    A clock-driven caller must be the best-behaved one we have."""
    started = []
    monkeypatch.setattr(bb, "_start_refresh", lambda: started.append(1) or True)
    bb._BREAKER.fail(rate_limited=True)      # opens it
    assert bb._BREAKER.state()["open"] is True

    # One tick's worth of the loop body, without the sleeps.
    if bb.is_configured() and not bb._BREAKER.state()["open"]:
        bb._start_refresh()
    assert not started


def test_a_refresher_tick_does_not_spend_the_breakers_probe_request():
    """`allow()` lets a single request through once the cooldown elapses and resets the
    breaker as a side effect. A background tick that called it would consume that probe
    ahead of a real reader — so the loop must test state() instead."""
    import inspect
    body = inspect.getsource(bb._refresher_loop)
    assert "_BREAKER.state()" in body
    assert ".allow()" not in body


def test_the_refresher_survives_a_failing_tick(monkeypatch):
    """This thread has to outlive any single failure — if it dies, the snapshot silently
    stops being refreshed and nothing says so."""
    boom = []

    def _explode():
        boom.append(1)
        raise RuntimeError("basisboard is having a day")

    monkeypatch.setattr(bb, "_start_refresh", _explode)
    monkeypatch.setattr(bb, "_REFRESHER_BOOT_DELAY_S", 0)
    monkeypatch.setattr(bb, "_ANALYTICS_TTL_S", 0.01)

    stop = []
    real_sleep = time.sleep

    def _sleep(_s):
        if len(boom) >= 3:
            stop.append(1)
            raise SystemExit                 # break the infinite loop from inside
        real_sleep(0)

    monkeypatch.setattr(bb.time, "sleep", _sleep)
    with pytest.raises(SystemExit):
        bb._refresher_loop()
    assert len(boom) >= 3, "the loop stopped ticking after the first failure"
