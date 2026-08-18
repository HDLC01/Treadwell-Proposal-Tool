"""Basisboard rate-limiting must not be able to take the whole tool down.

On 2026-08-01 proposals.wetreadwell.com was down for eleven hours and nothing alerted
anyone. Basisboard was rate-limiting us in bursts that cleared on their own. Their limit
wasn't the bug — ours was:

  * every rejected request slept ~7.5s through four retries INSIDE a threadpool thread;
  * the build locks made the next caller block on the lock, holding another thread;
  * FastAPI serves every sync route from that same pool, so once it filled, pages
    stopped — and `/healthz` stopped with them, which is why the container reported
    unhealthy for eleven hours while the notification bell kept answering 401s from
    async middleware that needs no thread.

So these tests are about threads and time, not about data. The rule they encode: a
rate-limited Basisboard makes the Lead Inbox, Bid Pipeline and Analytics go quiet, and
never costs a request thread that a page needs.
"""
import threading
import time

import pytest

import basisboard_client as bb


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    bb._BREAKER.ok()
    bb._meta_cache.clear()
    bb._pipeline_cache.clear()
    bb._inbox_cache.clear()
    bb._last_good.clear()
    yield
    bb._BREAKER.ok()
    bb._last_good.clear()


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._payload = payload or {}
        self.headers = {}
        self.request = None

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    """Counts calls and sleeps, so a test can assert on both."""

    def __init__(self, code=200, payload=None):
        self.code, self.payload, self.calls = code, payload, 0

    def get(self, url, params=None):
        self.calls += 1
        return _Resp(self.code, self.payload)


@pytest.fixture
def no_sleep(monkeypatch):
    """Record sleeps instead of taking them — the point is HOW LONG a thread would be
    held, and a test that actually waited 7.5s would be a test nobody runs."""
    slept = []
    monkeypatch.setattr(bb.time, "sleep", lambda s: slept.append(s))
    monkeypatch.setattr(bb._PACER, "wait", lambda: None)
    return slept


# ── the breaker ─────────────────────────────────────────────────────────────
def test_a_rate_limit_stops_the_retries_immediately(no_sleep):
    """The behaviour that caused the outage: four retries with doubling backoff meant
    ~7.5s of sleeping per rejected request, inside a request thread. One 429 is a
    definite "stop asking", so it must not be slept through three more times."""
    c = _Client(429)
    with pytest.raises(bb.BasisboardUnavailable):
        bb._get(c, "/stages")
    assert c.calls == 1, "kept hammering after a 429"
    assert no_sleep == [], "slept in a request thread after being told to stop"


def test_one_rate_limit_opens_the_breaker(no_sleep):
    c = _Client(429)
    with pytest.raises(bb.BasisboardUnavailable):
        bb._get(c, "/stages")
    assert bb.breaker_state()["open"] is True


def test_an_open_breaker_makes_no_call_at_all(no_sleep):
    c = _Client(429)
    with pytest.raises(bb.BasisboardUnavailable):
        bb._get(c, "/stages")
    before = c.calls
    for _ in range(5):
        with pytest.raises(bb.BasisboardUnavailable):
            bb._get(c, "/stages")
    assert c.calls == before, "dialled out while the breaker was open"
    assert no_sleep == []


def test_a_single_blip_does_not_open_it(no_sleep, monkeypatch):
    """A 500 or a dropped connection may be one bad moment. Only a rate limit — or
    repeated failure — is worth refusing everything for two minutes."""
    c = _Client(500)
    with pytest.raises(Exception):
        bb._get(c, "/stages")
    assert bb.breaker_state()["open"] is False
    assert bb.breaker_state()["fails"] == 1


def test_repeated_failure_opens_it_too(no_sleep):
    c = _Client(503)
    for _ in range(bb._BREAKER_FAILS):
        with pytest.raises(Exception):
            bb._get(c, "/stages")
    assert bb.breaker_state()["open"] is True


def test_it_closes_again_after_the_cooldown(no_sleep, monkeypatch):
    c = _Client(429)
    with pytest.raises(bb.BasisboardUnavailable):
        bb._get(c, "/stages")
    assert bb.breaker_state()["open"] is True
    # Jump past the cooldown rather than waiting two real minutes.
    base = time.monotonic
    monkeypatch.setattr(bb.time, "monotonic",
                        lambda: base() + bb._BREAKER_COOLDOWN_S + 1)
    assert bb.breaker_state()["open"] is False
    ok = _Client(200, {"stages": []})
    assert bb._get(ok, "/stages") == {"stages": []}
    assert ok.calls == 1


def test_a_success_clears_the_count(no_sleep):
    c = _Client(500)
    with pytest.raises(Exception):
        bb._get(c, "/stages")
    assert bb.breaker_state()["fails"] == 1
    bb._get(_Client(200, {"stages": []}), "/stages")
    assert bb.breaker_state()["fails"] == 0


# ── what the views do while it's open ───────────────────────────────────────
def test_the_pipeline_serves_the_last_good_copy_rather_than_an_error(monkeypatch):
    """Yesterday's board beats an error page. The TTL cache can't do this job — it
    expires exactly when an outage means you most want the stale copy."""
    good = {"ok": True, "configured": True, "projects": [{"id": "p1"}]}
    monkeypatch.setattr(bb, "_build_pipeline", lambda: good)
    assert bb.get_pipeline()["projects"] == [{"id": "p1"}]

    bb._pipeline_cache.clear()                 # TTL lapses
    bb._BREAKER.fail(rate_limited=True)        # and Basisboard starts refusing
    out = bb.get_pipeline()
    assert out["projects"] == [{"id": "p1"}]
    assert out["stale"] is True, "served stale data without saying so"


def test_the_pipeline_says_something_useful_with_no_cached_copy(monkeypatch):
    bb._BREAKER.fail(rate_limited=True)
    out = bb.get_pipeline()
    assert out["ok"] is False and out["skipped"] is True
    assert "rate-limiting" in out["error"]


def test_the_inbox_does_the_same(monkeypatch):
    good = {"ok": True, "configured": True, "messages": [{"id": "m1"}], "stats": {}}
    monkeypatch.setattr(bb, "_build_inbox", lambda status: good)
    assert bb.get_inbox()["messages"] == [{"id": "m1"}]
    bb._inbox_cache.clear()
    bb._BREAKER.fail(rate_limited=True)
    out = bb.get_inbox()
    assert out["messages"] == [{"id": "m1"}] and out["stale"] is True


def test_the_inbox_always_carries_messages_and_stats(monkeypatch):
    """Callers iterate it blindly — `leads.merge_inbox` walks `messages` without
    checking `ok` first, so a shape change here is a TypeError in the Lead Inbox."""
    bb._BREAKER.fail(rate_limited=True)
    out = bb.get_inbox()
    assert out["messages"] == [] and out["stats"] == {}


def test_an_open_breaker_never_reaches_the_builder(monkeypatch):
    called = []
    monkeypatch.setattr(bb, "_build_pipeline", lambda: called.append(1) or {"ok": True})
    bb._BREAKER.fail(rate_limited=True)
    bb.get_pipeline()
    assert called == [], "built (and so dialled out) with the breaker open"


# ── the lock: the part that actually filled the pool ────────────────────────
def test_a_waiting_request_gives_up_instead_of_holding_a_thread(monkeypatch):
    """THE fix. `with _BUILD_LOCK` meant every concurrent caller queued behind a holder
    that was sleeping through retries — each waiter burning a threadpool thread that a
    page needed. The wait is now bounded, so the pool drains instead of filling."""
    monkeypatch.setattr(bb, "_BUILD_WAIT_S", 0)     # a stand-in for "already too long"
    bb._BUILD_LOCK.acquire()                        # pretend another thread is building
    try:
        t0 = time.monotonic()
        out = bb.get_pipeline()
        elapsed = time.monotonic() - t0
    finally:
        bb._BUILD_LOCK.release()
    # The property is BOUNDED, not fast: the waiter must give the thread back rather than queue
    # behind a holder that is sleeping through retries. 10s is deliberately loose because this
    # figure is now measured on a machine running the suite across every core (`-n auto`), where a
    # tight bound measures CPU contention rather than the lock. `_BUILD_WAIT_S` is 0 here, so a
    # regression to the old unbounded `with _BUILD_LOCK` would block until the holder released —
    # which never happens on this thread — and blow any bound at all.
    assert elapsed < 10, f"waited {elapsed:.1f}s on a busy lock"
    assert out["busy"] is True


def test_a_waiting_request_prefers_the_last_good_copy(monkeypatch):
    monkeypatch.setattr(bb, "_BUILD_WAIT_S", 0)
    bb._last_good["pipeline"] = {"ok": True, "projects": [{"id": "old"}]}
    bb._BUILD_LOCK.acquire()
    try:
        out = bb.get_pipeline()
    finally:
        bb._BUILD_LOCK.release()
    assert out["projects"] == [{"id": "old"}] and out["stale"] is True


def test_the_lock_is_released_when_a_build_raises(monkeypatch):
    """A lock leaked on the error path would wedge the view permanently — every later
    request would hit the bounded wait and serve stale data forever."""
    def boom():
        raise RuntimeError("upstream down")

    monkeypatch.setattr(bb, "_build_pipeline", boom)
    bb.get_pipeline()
    assert bb._BUILD_LOCK.acquire(blocking=False) is True
    bb._BUILD_LOCK.release()


def test_concurrent_cold_readers_still_coalesce_into_one_build(monkeypatch):
    """The bounded wait must not throw away the reason the lock exists: ten people
    opening the board at once should cost ONE fetch, not ten."""
    builds = []

    def slow_build():
        builds.append(1)
        time.sleep(0.2)
        return {"ok": True, "configured": True, "projects": []}

    monkeypatch.setattr(bb, "_build_pipeline", slow_build)
    outs, threads = [], []
    for _ in range(6):
        t = threading.Thread(target=lambda: outs.append(bb.get_pipeline()))
        threads.append(t)
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert len(builds) == 1, f"{len(builds)} builds for 6 concurrent readers"
    assert all(o.get("ok") for o in outs)


# ── the healthcheck ─────────────────────────────────────────────────────────
def test_healthz_needs_no_threadpool_thread():
    """It was a plain `def`, so FastAPI ran it in the shared threadpool — the very pool
    the sleeping retries had filled. That is why the container reported unhealthy for
    eleven hours while the app was technically alive: the probe was queued behind the
    thing it was supposed to be reporting on."""
    import inspect

    import main
    assert inspect.iscoroutinefunction(main.healthz), (
        "/healthz is sync again — application load can starve it and the healthcheck "
        "will lie exactly when it matters")


def test_healthz_does_no_io():
    """A liveness probe that calls out can fail for reasons that have nothing to do with
    whether this process is alive."""
    import main
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True}


# ── the admin view ──────────────────────────────────────────────────────────
def test_an_admin_can_see_that_we_are_skipping_basisboard(monkeypatch):
    """Shedding the load silently would just make the Lead Inbox quietly wrong instead of
    making the site slow. Somebody has to be able to see it."""
    import main
    import profiles
    from fastapi.testclient import TestClient
    client = TestClient(main.app)
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})

    body = client.get("/api/admin/health").json()
    assert body["basisboard"]["open"] is False
    assert "answering normally" in body["basisboard"]["note"]

    bb._BREAKER.fail(rate_limited=True)
    body = client.get("/api/admin/health").json()
    assert body["basisboard"]["open"] is True
    assert body["basisboard"]["reopens_in_s"] > 0
    assert "rate-limited" in body["basisboard"]["note"]


def test_the_health_view_is_admin_only(monkeypatch):
    import main
    import profiles
    from fastapi.testclient import TestClient
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"email": e, "role": "user"})
    assert TestClient(main.app).get("/api/admin/health").status_code == 403
