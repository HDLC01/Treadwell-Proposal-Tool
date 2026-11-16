"""Plan vs Actual, the daily refresh (#784): every morning at 5:00 AM Central the same step as
"Refresh now" runs by itself, and every good run keeps one snapshot of each Project's figures.

Built like the 6 AM digest (backend/digest_worker.py): a daemon thread started from a startup hook,
an at-most-once-a-day stamp on the data volume, never a thread under pytest. Exercised two ways:
the schedule as pure functions with injected instants (the dev box's clock is ~13 hours ahead of
Central, so nothing here reads it), and the run itself through pva_refresh_worker.run_once() and the
HTTP API with test_raken_actuals' fake Google calendar and fake Raken, and conftest's fake Supabase
client for the snapshots. The claims that cost something when they are wrong:

  * 5:00 AM is Central's, across both DST changes; a container restarted after 5:00 still runs that
    day, and never twice in one day.
  * The run is "Refresh now"'s own step; a run already going is waited for, never doubled.
  * A persistent 429 or a used-up daily quota stops the run and keeps the last numbers, with their
    "as of" time; never blank, never a 500.
  * One snapshot row per Project per Central day; a second good run that day replaces it; a table
    not applied yet is logged once and nothing else changes.

"Today" is Wednesday 2026-11-18 (Central). PUBLIC REPO: every job, project, number and id below is
made up.
"""
import datetime as dt
import threading
import time

import httpx
import pytest

import plan_vs_actual
import pva_refresh_worker as worker
import pva_snapshots
import raken_actuals
from test_plan_vs_actual import mob
from test_raken_actuals import (JOB, _clean, by_key, card, client, fake, get, google,  # noqa: F401
                                project, refresh)

UTC = dt.timezone.utc


def at(y, m, d, hh, mm=0):
    return dt.datetime(y, m, d, hh, mm, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _isolate_state(tmp_path, monkeypatch):
    """Every test gets its own stamp file: a leaked `last_run` would make a schedule test vacuous."""
    monkeypatch.setattr(worker, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(worker, "_STATE_FILE", tmp_path / "pva_refresh_state.json")
    monkeypatch.setattr(worker, "_MEM_STATE", {})


# ── when it runs ──────────────────────────────────────────────────────────────
def test_it_waits_for_five_in_the_morning_central():
    # November is CST (UTC-6): 10:59 UTC is 4:59 AM, 11:00 UTC is 5:00 AM.
    assert worker.should_run({}, at(2026, 11, 18, 10, 59)) is False
    assert worker.should_run({}, at(2026, 11, 18, 11, 0)) is True


def test_a_day_already_run_does_not_run_again_and_the_next_day_does():
    assert worker.should_run({"last_run": "2026-11-18"}, at(2026, 11, 18, 20)) is False
    assert worker.should_run({"last_run": "2026-11-17"}, at(2026, 11, 18, 11)) is True
    assert worker.should_run({"last_run": "2026-11-18"}, at(2026, 11, 19, 11)) is True


def test_the_day_is_centrals_not_utcs():
    """03:00 UTC on the 19th is 9 PM on the 18th in Central: the 18th's stamp still holds, and the
    19th's run waits for 5:00 AM Central, not midnight UTC."""
    late = at(2026, 11, 19, 3)
    assert worker.biz_now(late).date().isoformat() == "2026-11-18"
    assert worker.should_run({"last_run": "2026-11-18"}, late) is False
    assert worker.should_run({"last_run": "2026-11-18"}, at(2026, 11, 19, 10, 30)) is False


@pytest.mark.parametrize("before, after", [
    # Summer (CDT, UTC-5): 5:00 AM is 10:00 UTC.
    (at(2026, 7, 15, 9, 59), at(2026, 7, 15, 10, 0)),
    # The morning clocks spring forward (Sun 2026-03-08, 2 AM -> 3 AM): 5:00 AM is CDT, 10:00 UTC.
    (at(2026, 3, 8, 9, 59), at(2026, 3, 8, 10, 0)),
    # The morning clocks fall back (Sun 2026-11-01, 2 AM -> 1 AM): 5:00 AM is CST, 11:00 UTC.
    (at(2026, 11, 1, 10, 59), at(2026, 11, 1, 11, 0)),
])
def test_five_in_the_morning_is_centrals_across_daylight_saving(before, after):
    assert worker.should_run({}, before) is False
    assert worker.should_run({}, after) is True


# ── the run ───────────────────────────────────────────────────────────────────
def raken_clock(monkeypatch, when):
    """raken_actuals' clock: the "as of" stamp and the 10-minute cooldown read it."""
    monkeypatch.setattr(raken_actuals, "now_utc", lambda: when)


def linked(fake):
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-17", "w-1", 8)]


def test_a_container_restarted_after_five_runs_that_day_once(client, google, fake, monkeypatch):
    google.events = [JOB]
    linked(fake)
    worker._tick(at(2026, 11, 18, 13, 15))              # 7:15 AM Central, never stamped today
    assert fake.project_calls == 1, "the morning's refresh ran late, not never"
    assert worker.load_state()["last_run"] == "2026-11-18"
    worker._tick(at(2026, 11, 18, 13, 20))
    monkeypatch.setattr(worker, "_MEM_STATE", {})       # a restart: only the file on the volume
    worker._tick(at(2026, 11, 18, 14, 0))
    assert fake.project_calls == 1, "it ran twice in one day"
    raken_clock(monkeypatch, at(2026, 11, 19, 11, 1))
    worker._tick(at(2026, 11, 19, 11, 0))               # 5:00 AM Central the next day
    assert fake.project_calls == 2, "the next morning did not run"


def test_the_run_is_the_refresh_now_step(monkeypatch):
    seen = []
    monkeypatch.setattr(plan_vs_actual, "refresh",
                        lambda **kw: seen.append(kw) or {"ok": True, "projects": [], "raken": {}})
    worker.run_once(at(2026, 11, 18, 11))
    assert seen == [{"wait": True}], "the daily run must call the same step, waiting its turn"


def test_a_refresh_now_already_going_is_waited_for_not_doubled(client, google, fake):
    google.events = [JOB]
    linked(fake)
    fake.gate = threading.Event()
    pressed, ran = [], []
    first = threading.Thread(target=lambda: pressed.append(client.post("/api/project-analytics/refresh")))
    first.start()
    try:
        assert fake.entered.wait(5), "the press never reached Raken"
        daily = threading.Thread(target=lambda: ran.append(worker.run_once(at(2026, 11, 18, 11))))
        daily.start()
        time.sleep(0.3)
        assert daily.is_alive(), "the daily run did not wait for the press"
    finally:
        fake.gate.set()
        first.join(15)
    daily.join(15)
    assert not daily.is_alive()
    assert fake.project_calls == 1, "Raken was read twice"
    assert by_key(ran[0])["job:26.501"]["raken"]["actual_hours"] == 16, "the press's numbers"
    assert ran[0]["raken"]["refreshing"] is False


def test_a_refresh_now_pressed_during_the_daily_run_answers_at_once_and_raken_is_read_once(
        client, google, fake):
    google.events = [JOB]
    linked(fake)
    fake.gate = threading.Event()
    ran = []
    daily = threading.Thread(target=lambda: ran.append(worker.run_once(at(2026, 11, 18, 11))))
    daily.start()
    try:
        assert fake.entered.wait(5), "the daily run never reached Raken"
        started = time.monotonic()
        pressed = refresh(client)
        assert time.monotonic() - started < 5, "the press held a server thread for the whole read"
    finally:
        fake.gate.set()
        daily.join(15)
    assert pressed["raken"]["refreshing"] is True, "the page polls until the daily run is done"
    assert get(client)["raken"]["refreshing"] is False
    assert fake.project_calls == 1


# ── outages ───────────────────────────────────────────────────────────────────
def limited(fake, monkeypatch, body):
    """Every Raken data call answers 429 with `body` from now on (the sign-in still works)."""
    real = fake._handle

    def answer(request):
        if request.url.host == "developer.rakenapp.com":
            return httpx.Response(429, json=body)
        return real(request)
    monkeypatch.setattr(fake, "_handle", answer)


@pytest.mark.parametrize("body, message", [
    ({"message": "Too many requests"},
     "Raken is limiting requests right now. Try again later."),
    ({"message": "Daily limit exceeded"},
     "Raken's daily request limit is used up. Try again tomorrow."),
])
def test_a_persistent_429_or_the_daily_quota_stops_the_run_and_keeps_the_last_numbers(
        client, google, fake, monkeypatch, body, message):
    google.events = [JOB]
    linked(fake)
    refresh(client)                                     # Wednesday 9:05 AM Central, a good read
    limited(fake, monkeypatch, body)
    raken_clock(monkeypatch, at(2026, 11, 19, 11, 1))
    worker._tick(at(2026, 11, 19, 11, 0))               # Thursday's 5:00 AM run
    assert worker.load_state()["last_run"] == "2026-11-19", "the day is stamped: no retry storm"
    shown = get(client)
    assert shown["raken"]["state"] == "connected" and shown["raken"]["stale"] is True
    assert shown["raken"]["message"] == message
    assert shown["raken"]["as_of"] == "2026-11-18T09:05:00-06:00", "the last good read's age"
    assert by_key(shown)["job:26.501"]["raken"]["actual_hours"] == 16, "never blank"
    calls = len(fake.card_calls) + fake.project_calls
    worker._tick(at(2026, 11, 19, 11, 30))
    assert len(fake.card_calls) + fake.project_calls == calls, "retried the same day"


def test_raken_unreachable_on_the_daily_run_keeps_the_last_numbers_and_never_500s(
        client, google, fake, monkeypatch):
    google.events = [JOB]
    linked(fake)
    refresh(client)
    fake.down = True
    raken_clock(monkeypatch, at(2026, 11, 19, 11, 1))
    body = worker.run_once(at(2026, 11, 19, 11, 0))
    assert body["raken"]["stale"] is True
    assert body["raken"]["message"] == "Raken could not be reached."
    assert by_key(body)["job:26.501"]["raken"]["actual_hours"] == 16
    r = client.get("/api/project-analytics")
    assert r.status_code == 200 and r.json()["raken"]["as_of"] == "2026-11-18T09:05:00-06:00"


def test_a_google_failure_on_the_daily_run_keeps_the_last_numbers(client, google, fake, monkeypatch):
    google.events = [JOB]
    linked(fake)
    refresh(client)
    google.fail = True
    import project_calendar as pc
    pc.cache_clear()
    raken_clock(monkeypatch, at(2026, 11, 19, 11, 1))
    body = worker.run_once(at(2026, 11, 19, 11, 0))
    assert body["ok"] is True and body["error"]
    r = client.get("/api/project-analytics")
    assert r.status_code == 200
    assert raken_actuals.load()["result"]["days"]["r-1"], "the kept Raken read was not shrunk"


# ── snapshots ─────────────────────────────────────────────────────────────────
@pytest.fixture
def snaps(monkeypatch, fake_supabase):
    """conftest's in-memory Supabase client, standing in for the data store's pva_snapshots."""
    db = fake_supabase()
    monkeypatch.setattr(pva_snapshots, "get_client", lambda: db)
    return db


def rows(db):
    return sorted(db.store.get("pva_snapshots", []), key=lambda r: (r["snap_date"], r["project_key"]))


SECOND = mob("k", "26.502, Example Depot (2) (Lee)", "2026-11-16", "2026-11-20", "9")


def test_a_good_refresh_now_keeps_one_snapshot_row_per_project(client, google, fake, snaps):
    google.events = [JOB, SECOND]
    linked(fake)
    refresh(client)
    got = rows(snaps)
    assert [(r["project_key"], r["snap_date"]) for r in got] == [
        ("job:26.501", "2026-11-18"), ("job:26.502", "2026-11-18")]
    one = got[0]
    assert one["ran_at"] == "2026-11-18T09:05:00-06:00", "when the read ran, in Central"
    f = one["figures"]
    assert f["job_number"] == "26.501" and f["planned_hours"] == 2 * 3 * 8
    assert f["workdays_so_far"] == 2 and f["statuses"] == ["on_plan"]
    assert f["raken"]["state"] == "linked" and f["raken"]["actual_hours"] == 16
    assert f["raken"]["days_clocked"] == 2
    assert got[1]["figures"]["statuses"] == ["not_linked"]


def test_a_second_good_run_the_same_day_replaces_the_row(client, google, fake, snaps, monkeypatch):
    google.events = [JOB]
    linked(fake)
    refresh(client)                                     # 9:05 AM Central
    fake.cards.append(card("r-1", "2026-11-17", "w-2", 4))
    raken_clock(monkeypatch, at(2026, 11, 18, 20, 0))   # 2:00 PM Central, past the cooldown
    refresh(client)
    got = rows(snaps)
    assert [(r["project_key"], r["snap_date"]) for r in got] == [("job:26.501", "2026-11-18")]
    assert got[0]["figures"]["raken"]["actual_hours"] == 20, "the later run's figures"
    assert got[0]["ran_at"] == "2026-11-18T14:00:00-06:00"


def test_the_daily_run_keeps_a_snapshot_and_the_next_day_adds_its_own(
        client, google, fake, snaps, monkeypatch):
    google.events = [JOB]
    linked(fake)
    raken_clock(monkeypatch, at(2026, 11, 18, 11, 0))
    worker._tick(at(2026, 11, 18, 11, 0))
    assert [(r["project_key"], r["snap_date"]) for r in rows(snaps)] == [
        ("job:26.501", "2026-11-18")]
    import project_calendar as pc
    monkeypatch.setattr(pc, "today_central", lambda: dt.date(2026, 11, 19))
    pc.cache_clear()
    raken_clock(monkeypatch, at(2026, 11, 19, 11, 0))
    worker._tick(at(2026, 11, 19, 11, 0))
    got = rows(snaps)
    assert [(r["project_key"], r["snap_date"]) for r in got] == [
        ("job:26.501", "2026-11-18"), ("job:26.501", "2026-11-19")]
    assert got[0]["ran_at"] == "2026-11-18T05:00:00-06:00", "yesterday's row is left as it was"


def test_a_run_that_did_not_read_raken_keeps_no_snapshot(client, google, fake, snaps, monkeypatch):
    """A failed read, and a press inside the cooldown (it only answers from the kept read), keep
    none: only the run that read Raken does."""
    google.events = [JOB]
    linked(fake)
    fake.down = True
    refresh(client)
    assert rows(snaps) == [], "a failed read kept a snapshot"
    fake.down = False
    refresh(client)
    kept = [dict(r) for r in rows(snaps)]
    assert len(kept) == 1
    raken_clock(monkeypatch, at(2026, 11, 18, 15, 6))   # a minute later, inside the cooldown
    snaps.store["pva_snapshots"] = []
    refresh(client)
    assert rows(snaps) == [], "a press inside the cooldown wrote again"


def test_a_429_on_the_daily_run_keeps_no_snapshot_and_leaves_the_last_one(
        client, google, fake, snaps, monkeypatch):
    google.events = [JOB]
    linked(fake)
    refresh(client)
    limited(fake, monkeypatch, {"message": "Too many requests"})
    raken_clock(monkeypatch, at(2026, 11, 19, 11, 1))
    worker._tick(at(2026, 11, 19, 11, 0))
    assert [r["snap_date"] for r in rows(snaps)] == ["2026-11-18"]


def test_a_google_failure_keeps_no_snapshot(client, google, fake, snaps, monkeypatch):
    google.events = [JOB]
    linked(fake)
    google.fail = True
    body = refresh(client)
    assert body["error"]
    assert rows(snaps) == []


def test_a_stale_calendar_copy_keeps_no_snapshot_even_when_raken_reads(
        client, google, fake, snaps, monkeypatch):
    """Google failing after a good read serves the last copy as stale: the plan it gives may be out
    of date, so the day's snapshot is not taken from it."""
    google.events = [JOB]
    linked(fake)
    refresh(client)
    snaps.store["pva_snapshots"] = []
    google.fail = True
    raken_clock(monkeypatch, at(2026, 11, 18, 20, 0))   # past the cooldown: Raken is read again
    body = refresh(client)
    assert body["stale"] is True and [p["key"] for p in body["projects"]] == ["job:26.501"]
    assert body["raken"]["as_of"] == "2026-11-18T14:00:00-06:00", "Raken was read"
    assert rows(snaps) == []


class Missing(Exception):
    """What supabase-py raises for a table PostgREST does not know: an APIError carrying `code`."""
    code = "PGRST205"


class Broken:
    def __init__(self, exc):
        self.exc, self.calls = exc, 0

    def table(self, name):
        return self

    def upsert(self, *a, **k):
        return self

    def execute(self):
        self.calls += 1
        raise self.exc


@pytest.mark.parametrize("exc", [Missing("made-up: relation not in the schema cache"),
                                 RuntimeError("made-up: the data store timed out")])
def test_a_snapshot_table_not_there_yet_or_a_store_failure_never_fails_the_refresh(
        client, google, fake, monkeypatch, caplog, exc):
    google.events = [JOB]
    linked(fake)
    broken = Broken(exc)
    monkeypatch.setattr(pva_snapshots, "get_client", lambda: broken)
    r = client.post("/api/project-analytics/refresh")
    assert r.status_code == 200, r.text
    assert by_key(r.json())["job:26.501"]["raken"]["actual_hours"] == 16
    assert broken.calls == 1
    assert "made-up" not in caplog.text, "the store's own words reached the log"


def test_a_missing_snapshot_table_is_logged_once(client, google, fake, monkeypatch, caplog):
    google.events = [JOB]
    linked(fake)
    monkeypatch.setattr(pva_snapshots, "get_client", lambda: Broken(Missing("made-up")))
    refresh(client)
    raken_clock(monkeypatch, at(2026, 11, 18, 20, 0))
    refresh(client)
    lines = [r for r in caplog.records if "pva_snapshots table is not on this database" in r.getMessage()]
    assert len(lines) == 1


# ── switching it off, and no thread under tests ───────────────────────────────
def test_the_worker_never_starts_under_pytest():
    assert worker.ensure_started() is False


@pytest.mark.parametrize("value, on", [(None, True), ("on", True), ("off", False), ("0", False),
                                       ("false", False), (" OFF ", False)])
def test_the_switch_is_on_unless_turned_off(monkeypatch, value, on):
    if value is None:
        monkeypatch.delenv("PVA_REFRESH_ENABLED", raising=False)
    else:
        monkeypatch.setenv("PVA_REFRESH_ENABLED", value)
    assert worker.enabled() is on


def test_switched_off_the_tick_does_nothing(monkeypatch):
    monkeypatch.setenv("PVA_REFRESH_ENABLED", "off")
    monkeypatch.setattr(plan_vs_actual, "refresh",
                        lambda **kw: pytest.fail("the daily run ran while switched off"))
    worker._tick(at(2026, 11, 18, 11))
    assert worker.load_state() == {}


def test_the_startup_hook_starts_the_worker(monkeypatch):
    import main
    started = []
    monkeypatch.setattr(worker, "ensure_started", lambda: started.append(True) or True)
    main._start_pva_refresh()
    assert started == [True]


# ── the table, on both databases ──────────────────────────────────────────────
@pytest.mark.parametrize("name", ["ops/pva_snapshots.sql", "supabase_schema.sql",
                                  "staging/schema_pg.sql"])
def test_the_snapshot_table_is_declared_with_its_grant_wherever_it_is_applied(name):
    """Prod and staging are separate databases: a table on only one of them is a feature that keeps
    nothing on the other. The upsert's conflict target must be the table's primary key, and the
    grant goes beside the table (a blanket grant only covers tables that existed when it ran)."""
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parents[1] / name).read_text(encoding="utf-8")
    block = sql[sql.index("create table if not exists public.pva_snapshots ("):]
    block = block[:block.index(");")]
    for col in ("project_key text not null", "snap_date   date not null",
                "figures     jsonb not null", "ran_at      timestamptz"):
        assert col in block, (name, col)
    assert "primary key (project_key, snap_date)" in block, name
    assert pva_snapshots.ON_CONFLICT == "project_key,snap_date"
    assert "grant select, insert, update, delete on public.pva_snapshots to service_role;" in sql
