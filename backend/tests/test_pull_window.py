"""How far back we pull BasisBoard data — one window, for the whole company.

Hanz, 2026-08-12: "this is for the analytics. We need to create a date range on when we will be
getting data from the basisboard API becuase the analytics will eventually be moved to this
proposal tool using the data from hjere", then "we need a date pciker like the custom date in the
analytics for when it pulls data". Asked, he chose one shared window over per-viewer pulls.

The constraint that shapes all of this: BasisBoard's API has NO date filter. It offers
`sort[bidDeadline]` (a sort, with an unsorted fallback) and limit/offset paging, and nothing else.
So the window is ours to enforce, after the fetch, and every question below — which dates count,
what happens to a bid with no dates, what the Bid Calendar sees — is a decision this file records
rather than something the API answered for us.

Reused from the existing analytics tests: the fake `_get`, so no test here touches a network.
"""
import json
import threading

import pytest
from fastapi.testclient import TestClient

import basisboard_client as bb
import main
import pull_window
from test_basisboard_analytics import _clear, _fake_get


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    """A window file per test. The real one lives on the data volume."""
    monkeypatch.setattr(pull_window, "_FILE", tmp_path / "analytics_pull_window.json")
    monkeypatch.setattr(pull_window, "_DATA_DIR", tmp_path)
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    yield
    _clear()


def _rows(payload):
    return {r["id"]: r for r in payload["projects"]}


# ── the store ─────────────────────────────────────────────────────────────────
def test_unset_means_all_time():
    """The default has to be today's behaviour exactly, or shipping this changes every number on
    the dashboard for a setting nobody has touched."""
    assert pull_window.get() == {"from": None, "to": None,
                                 "updated_at": None, "updated_by": None}
    assert pull_window.is_open() is True


def test_a_window_round_trips_with_who_and_when():
    out = pull_window.set("2024-01-01", "2026-08-01", "kyle@wetreadwell.com")
    assert out["from"] == "2024-01-01" and out["to"] == "2026-08-01"
    assert out["updated_by"] == "kyle@wetreadwell.com"
    assert out["updated_at"], "an org setting with no timestamp cannot be explained later"
    again = pull_window.get()
    assert (again["from"], again["to"], again["updated_by"]) == (
        "2024-01-01", "2026-08-01", "kyle@wetreadwell.com")
    assert pull_window.is_open() is False


def test_either_side_alone_is_a_window():
    pull_window.set("2025-01-01", None, "k@x.com")
    assert pull_window.get()["to"] is None and pull_window.is_open() is False
    pull_window.set(None, "2025-12-31", "k@x.com")
    assert pull_window.get()["from"] is None and pull_window.is_open() is False
    pull_window.set(None, None, "k@x.com")
    assert pull_window.is_open() is True, "clearing both sides must return to all-time"


def test_a_date_that_looks_real_but_is_not_is_refused():
    """The reason `validate` parses instead of pattern-matching. 2026-02-30 satisfies every
    plausible regex, and a window built on it would keep or drop rows by string luck."""
    for bad in ("2026-02-30", "2026-13-01", "08/13/2026", "yesterday", "2026-8-1x"):
        with pytest.raises(pull_window.PullWindowError):
            pull_window.validate(bad, None)


def test_a_backwards_window_is_refused():
    with pytest.raises(pull_window.PullWindowError):
        pull_window.validate("2026-08-01", "2024-01-01")
    # Equal is a single day, not an error.
    assert pull_window.validate("2026-08-01", "2026-08-01")["from"] == "2026-08-01"


def test_a_corrupt_file_reads_as_all_time():
    """Fail OPEN. A garbled byte costs a wider pull — today's behaviour — instead of an analytics
    page that cannot load."""
    pull_window._FILE.write_text("{not json", encoding="utf-8")
    assert pull_window.is_open() is True
    pull_window._FILE.write_text('["a", "list"]', encoding="utf-8")
    assert pull_window.is_open() is True


def test_a_hand_edited_backwards_file_reads_as_all_time():
    """from > to on disk would exclude every row and read as "the org has no bids" — the one
    failure mode that looks like data rather than a fault."""
    pull_window._FILE.write_text(json.dumps({"from": "2026-01-01", "to": "2020-01-01"}),
                                 encoding="utf-8")
    assert pull_window.is_open() is True


def test_a_failed_write_is_raised_not_swallowed():
    """An org setting that "saved" into one container's memory is worse than one that refused:
    the person who set it has no way to find out."""
    def boom(*a, **k):
        raise OSError("read-only volume")

    orig = type(pull_window._FILE).write_text
    try:
        type(pull_window._FILE).write_text = boom
        with pytest.raises(pull_window.PullWindowWriteError):
            pull_window.set("2024-01-01", None, "k@x.com")
    finally:
        type(pull_window._FILE).write_text = orig
    assert pull_window.is_open() is True, "a failed save must not appear to have taken effect"


def test_the_write_is_atomic(monkeypatch):
    """A write that dies halfway must leave the PREVIOUS window intact.

    Written as the failure, not as "a .tmp file is used": a direct write truncates the real file
    first, so a full disk or a killed container turns the org's setting into a corrupt file that
    reads as all-time. The tmp+replace exists for that, and this proves it by half-writing."""
    pull_window.set("2024-01-01", "2025-01-01", "kyle@wetreadwell.com")

    def half_then_die(self, data, encoding=None, **kw):
        self.write_bytes(b'{"from": "2030-01-')     # a plausible-looking partial file
        raise OSError("disk full")

    # A context, not monkeypatch.undo(): undo() reverts every patch on this test item, including
    # the autouse fixture's redirect of `_FILE` to tmp_path — which would send the assertion below
    # to read the REAL window on the data volume.
    with monkeypatch.context() as m:
        m.setattr(type(pull_window._FILE), "write_text", half_then_die)
        with pytest.raises(pull_window.PullWindowWriteError):
            pull_window.set("2026-01-01", None, "k@x.com")
    assert pull_window.get()["from"] == "2024-01-01", (
        "a failed write destroyed the window that was already stored")
    assert pull_window.get()["to"] == "2025-01-01"


# ── Central days ──────────────────────────────────────────────────────────────
def test_a_timestamp_is_placed_on_its_CENTRAL_day():
    """The Python twin of analytics-core.js's bizDay, and it has to be: 02:00 UTC on the 2nd is
    still the 1st in Kansas, so a raw-ISO comparison would keep a different set of bids than the
    dashboard shows for the same dates."""
    assert bb._central_day("2026-03-02T02:00:00Z") == "2026-03-01"
    assert bb._central_day("2026-03-02T18:00:00Z") == "2026-03-02"
    assert bb._central_day("2026-01-01T05:59:00.000Z") == "2025-12-31"
    assert bb._central_day(None) == ""
    assert bb._central_day("") == ""
    assert bb._central_day("not a date") == ""


def test_a_late_evening_bid_counts_on_the_day_it_was_submitted():
    """7pm Central on the 31st is the 1st in UTC. A month window that ends on the 31st has to
    keep it, or the dashboard's month total and the pull disagree."""
    row = {"submitted_at": "2026-04-01T01:30:00Z"}     # 8:30pm Central, Mar 31
    win = {"from": "2026-03-01", "to": "2026-03-31"}
    assert bb._row_in_pull_window(row, win, "2026-08-13") is True


# ── which rows survive ────────────────────────────────────────────────────────
def _row(**kw):
    base = {"awarded_at": None, "submitted_at": None, "lost_at": None,
            "created_at": None, "bid_deadline_at": None}
    base.update(kw)
    return base


def test_bounds_are_inclusive():
    win = {"from": "2026-03-01", "to": "2026-03-31"}
    assert bb._row_in_pull_window(_row(created_at="2026-03-01T12:00:00Z"), win, "2026-08-13")
    assert bb._row_in_pull_window(_row(created_at="2026-03-31T12:00:00Z"), win, "2026-08-13")
    assert not bb._row_in_pull_window(_row(created_at="2026-02-28T12:00:00Z"), win, "2026-08-13")
    assert not bb._row_in_pull_window(_row(created_at="2026-04-01T12:00:00Z"), win, "2026-08-13")


def test_ANY_of_the_five_dates_keeps_a_row():
    """Not deadline-only, which was the obvious design and is wrong twice over. A job created in
    2019 and awarded last month IS last month's win — "Won this year" would lose it."""
    old_job_won_recently = _row(created_at="2019-04-04T12:00:00Z",
                                bid_deadline_at="2019-05-01T12:00:00Z",
                                awarded_at="2026-07-15T12:00:00Z")
    win = {"from": "2026-01-01", "to": "2026-12-31"}
    assert bb._row_in_pull_window(old_job_won_recently, win, "2026-08-13") is True
    # And the reverse: a bid submitted in-window whose deadline has long passed.
    assert bb._row_in_pull_window(_row(submitted_at="2026-02-10T00:00:00Z",
                                       bid_deadline_at="2020-01-01T00:00:00Z"),
                                  win, "2026-08-13") is True


def test_a_row_with_no_dates_at_all_is_dropped_under_a_window():
    """It contributes to no number on the dashboard — every metric is keyed on a date — so
    dropping it loses nothing visible, and keeping it would make the row count lie."""
    assert bb._row_in_pull_window(_row(), {"from": "2026-01-01", "to": None}, "2026-08-13") is False
    # With no window, everything is kept — including this one.
    assert bb._row_in_pull_window(_row(), {"from": None, "to": None}, "2026-08-13") is True


def test_an_upcoming_deadline_survives_a_past_to_bound():
    """The Bid Calendar reads this same payload. Somebody looking at last year sets `to` to last
    December; next week's bids must not vanish off the calendar because of it."""
    win = {"from": "2025-01-01", "to": "2025-12-31"}
    upcoming = _row(created_at="2026-08-01T12:00:00Z", bid_deadline_at="2026-08-20T19:00:00Z")
    assert bb._row_in_pull_window(upcoming, win, "2026-08-13") is True
    # Today counts as upcoming — a bid due today is still due.
    today = _row(bid_deadline_at="2026-08-13T19:00:00Z")
    assert bb._row_in_pull_window(today, win, "2026-08-13") is True
    # Yesterday does not.
    past = _row(bid_deadline_at="2026-08-12T19:00:00Z")
    assert bb._row_in_pull_window(past, win, "2026-08-13") is False


# ── the built dataset ─────────────────────────────────────────────────────────
def test_no_window_builds_exactly_what_it_built_before():
    """The regression guard for everyone who has not set a window."""
    payload = bb._build_analytics()
    assert set(_rows(payload)) == {"p1", "p2", "p3", "parch"}     # pdel is deleted, always dropped
    assert payload["pull_window"]["from"] is None


def test_a_window_thins_the_history_and_says_so():
    pull_window.set("2026-01-01", "2026-12-31", "kyle@wetreadwell.com")
    payload = bb._build_analytics()
    ids = set(_rows(payload))
    assert "p2" in ids, "submitted Feb 2026 — in window"
    assert "p1" in ids, "awarded May 2026 — in window despite a 2024 creation"
    assert "parch" not in ids, "submitted Mar 2025, deadline-less, archived — out of window"
    assert payload["pull_window"]["from"] == "2026-01-01"
    assert payload["pull_window"]["updated_by"] == "kyle@wetreadwell.com"


def test_a_window_does_not_make_the_payload_read_as_truncated(monkeypatch):
    """`total`/`truncated` mean THE CAP — how much history exists versus how much we are allowed
    to fetch. `truncated` therefore counts what was FETCHED, not what survived the window:
    comparing against the filtered list makes every date range announce "showing the most recent N
    of M bids", i.e. reports a deliberate setting as lost data.

    Nothing is capped here — the ids the fake returns are exactly what gets fetched — so
    `truncated` must be False both open and windowed."""
    ids = [i for i in ("p1", "p2", "p3", "parch")]        # the deleted one is not offered at all
    monkeypatch.setattr(bb, "_fetch_project_ids", lambda *a, **k: (ids, len(ids)))

    open_payload = bb._build_analytics()
    assert open_payload["truncated"] is False and open_payload["shown"] == 4

    _clear()
    monkeypatch.setattr(bb, "_fetch_project_ids", lambda *a, **k: (ids, len(ids)))
    pull_window.set("2026-01-01", "2026-12-31", "k@x.com")
    payload = bb._build_analytics()
    assert payload["total"] == 4, "total is BasisBoard's count, not ours"
    assert payload["shown"] < 4, "the window kept everything"
    assert payload["shown"] == len(payload["projects"])
    assert payload["truncated"] is False, (
        "a date range now reads as lost bids: the page will say "
        '"showing the most recent %d of %d"' % (payload["shown"], payload["total"]))


def test_the_filter_lists_only_offer_what_survived():
    """Dimensions are derived AFTER the window, so a filter can never offer an option that
    matches nothing."""
    pull_window.set("2026-01-01", "2026-12-31", "k@x.com")
    payload = bb._build_analytics()
    assert "Gyp" not in payload["trades"], (
        "the only Gyp bid is out of window, so the trade filter must not offer it")


def test_every_payload_shape_carries_the_window():
    """Including the one served before anything has been fetched: a control that renders empty
    reads as "no window is set", which is a different and wrong statement."""
    building = bb.get_analytics()
    assert "pull_window" in building and building.get("building") is True
    pull_window.set("2024-01-01", None, "k@x.com")
    _clear()
    bb._analytics_last_good["snapshot"] = {"ok": True, "projects": [],
                                          "pull_window": {"from": "2024-01-01", "to": None}}
    stale = bb.get_analytics()
    assert stale["stale"] is True and stale["pull_window"]["from"] == "2024-01-01"


def test_an_old_snapshot_without_the_key_still_serves():
    """Snapshots written before this feature have no `pull_window`. The page must read a missing
    key as "all time" rather than break on the deploy that introduces it."""
    _clear()
    bb._analytics_last_good["snapshot"] = {"ok": True, "projects": [], "shown": 0, "total": 0}
    out = bb.get_analytics()
    assert out["stale"] is True
    assert out.get("pull_window") is None       # absent, not an error — the client treats it as open


# ── cache invalidation and the mid-build race ─────────────────────────────────
def test_changing_the_window_drops_the_cache_and_rebuilds_once(monkeypatch):
    bb._analytics_cache["analytics"] = {"ok": True, "projects": [], "pull_window": {}}
    starts = []
    monkeypatch.setattr(bb, "_start_refresh", lambda: starts.append(1) or True)
    bb.on_pull_window_changed()
    assert bb._analytics_cache.get("analytics") is None, "the old window would serve for a full TTL"
    assert len(starts) == 1, "one build, not one per reader"


def test_the_last_good_snapshot_survives_the_change(monkeypatch):
    """Real (if old) numbers flagged stale beat an empty "building…" page for ten seconds."""
    bb._analytics_last_good["snapshot"] = {"ok": True, "projects": [{"id": "p1"}]}
    monkeypatch.setattr(bb, "_start_refresh", lambda: True)
    bb.on_pull_window_changed()
    assert bb._analytics_last_good["snapshot"]["projects"] == [{"id": "p1"}]


def test_a_window_changed_mid_build_is_rebuilt_for(monkeypatch):
    """THE RACE. A build takes ~10s. Change the window while one is in flight and that build
    finishes carrying the OLD window, publishing it into the cache the save just cleared — pinning
    stale dates for a full TTL while the page's caption shows the new ones."""
    builds = []

    def build_then_move():
        # First build reads the window as it is now, and somebody edits it while we work.
        win = pull_window.get()
        builds.append(win)
        if len(builds) == 1:
            pull_window.set("2020-01-01", None, "somebody@x.com")
        return {"ok": True, "projects": [], "pull_window": win, "shown": 0, "total": 0}

    monkeypatch.setattr(bb, "_build_analytics", build_then_move)
    monkeypatch.setattr(bb, "_save_snapshot", lambda r: None)
    bb._ANALYTICS_REFRESH_LOCK.acquire(blocking=False)
    bb._refresh_analytics()
    assert len(builds) == 2, "the build published a window that had already been replaced"
    published = bb._analytics_cache.get("analytics")
    assert published["pull_window"]["from"] == "2020-01-01"


def test_a_window_that_keeps_moving_does_not_spin_the_api(monkeypatch):
    """Bounded, not `while`: somebody dragging a date input must not turn one build into an
    unbounded run of them."""
    builds = []

    def always_moving():
        builds.append(1)
        pull_window.set("20%02d-01-01" % (20 + len(builds)), None, "x@x.com")
        return {"ok": True, "projects": [], "pull_window": {"from": "stale"}}

    monkeypatch.setattr(bb, "_build_analytics", always_moving)
    monkeypatch.setattr(bb, "_save_snapshot", lambda r: None)
    bb._ANALYTICS_REFRESH_LOCK.acquire(blocking=False)
    bb._refresh_analytics()
    assert len(builds) <= 3, "the rebuild loop is unbounded: %d builds" % len(builds)


def test_the_store_is_safe_across_threads():
    """Two estimators saving at once must leave one whole window on disk, not a mix."""
    errors = []

    def worker(i):
        try:
            for _ in range(20):
                pull_window.set("20%02d-01-01" % (20 + i), None, "u%d@x.com" % i)
                pull_window.get()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert not errors, errors
    assert pull_window.get()["from"] in {"2020-01-01", "2021-01-01", "2022-01-01", "2023-01-01"}


# ── the route ─────────────────────────────────────────────────────────────────
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_user_email", lambda request: "kyle@wetreadwell.com")
    monkeypatch.setattr(main.basisboard_client, "on_pull_window_changed", lambda: None)
    return TestClient(main.app)


def test_the_route_saves_and_echoes_the_window(client):
    r = client.put("/api/analytics/pull-window", json={"from": "2024-01-01", "to": "2026-08-01"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pull_window"]["from"] == "2024-01-01"
    assert body["pull_window"]["to"] == "2026-08-01"
    assert pull_window.get()["from"] == "2024-01-01", "the response agreed but nothing was stored"


def test_the_route_stamps_the_signed_in_user_not_the_body(client):
    client.put("/api/analytics/pull-window",
               json={"from": "2024-01-01", "to": None})
    assert pull_window.get()["updated_by"] == "kyle@wetreadwell.com"


def test_the_route_rebuilds_the_dataset(monkeypatch):
    monkeypatch.setattr(main, "_user_email", lambda request: "k@x.com")
    called = []
    monkeypatch.setattr(main.basisboard_client, "on_pull_window_changed",
                        lambda: called.append(1))
    TestClient(main.app).put("/api/analytics/pull-window", json={"from": "2024-01-01"})
    assert called == [1], "the window changed and the dataset was left as it was"


def test_the_route_refuses_a_bad_date(client):
    r = client.put("/api/analytics/pull-window", json={"from": "2026-02-30"})
    assert r.status_code == 400
    assert pull_window.is_open() is True


def test_the_route_refuses_a_backwards_window(client):
    r = client.put("/api/analytics/pull-window", json={"from": "2026-08-01", "to": "2024-01-01"})
    assert r.status_code == 400


def test_a_typo_in_a_key_is_a_422_not_a_silent_no_op(client):
    """`extra="forbid"`: without it, {"form": ...} would save an empty window and report success
    while the old dates stayed in force."""
    r = client.put("/api/analytics/pull-window", json={"form": "2024-01-01"})
    assert r.status_code == 422
    assert pull_window.is_open() is True


def test_clearing_both_sides_is_allowed(client):
    pull_window.set("2024-01-01", "2025-01-01", "k@x.com")
    r = client.put("/api/analytics/pull-window", json={"from": None, "to": None})
    assert r.status_code == 200
    assert pull_window.is_open() is True, "there must be a way back to all-time"


def test_a_failed_save_is_a_500_and_invalidates_nothing(monkeypatch):
    monkeypatch.setattr(main, "_user_email", lambda request: "k@x.com")
    called = []
    monkeypatch.setattr(main.basisboard_client, "on_pull_window_changed", lambda: called.append(1))
    monkeypatch.setattr(main.pull_window, "set",
                        lambda *a, **k: (_ for _ in ()).throw(
                            pull_window.PullWindowWriteError("read-only volume")))
    r = TestClient(main.app).put("/api/analytics/pull-window", json={"from": "2024-01-01"})
    assert r.status_code == 500
    assert called == [], "the dataset was rebuilt for a window that was never stored"
