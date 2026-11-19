"""backend/bd/weekly_worker.py: the Friday weekly-10 worker, inside the proposal tool (#807).

Moved from BD's tests/test_weekly_worker.py. BD started its worker from a lifespan; the tool's
workers start from a startup hook (a lifespan would stop the tool's other startup hooks running),
so the lifespan tests became startup-hook tests. BD's seed is gone, so the batches are checked
against the fixture seed (bd/ops/fixture_seed.py) with the lists worked by hand below.

  * Switched off unless BD_WEEKLY_ENABLED is on (and the BD switch with it). Never a thread under
    pytest. Started from the tool's startup hooks, and the tool's other hooks still run.
  * The business clock is pinned (BD_NOW): before, at and after the run hour, on a Friday,
    Saturday and Sunday run day, all America/Chicago.
  * One batch per active salesperson and week, however often it ticks or restarts.
  * A tick that fails is logged and counted, and the thread keeps going.

THE FIXTURE SEED ON FRIDAY 6 NOV 2026, worked by hand (bd/priority.py's rules, scored on Nov 6):
  Avery (1) owns 21, 23, 25, 27, 30, 31. The rollover snoozes 301 and 302 (batch 201, open).
    31 Nora   maintenance, never followed up: due, pinned first.
    21 Dana   tried Nov 2 (4 days ago, so not in the 3-day cool-off): live call Oct 20, 17 days,
              on the team's quarterly BD cadence (her stored 12 a year is not used) 30 x 17 / 91.25
              = 5.6 -> 6; promised Thu Nov 5, past, +50; quote Oct 15 (22 days) +15; key account
              +20; 1 try since live +5 = 96 (follow-up).
    27 Lena   never contacted +40, key account +20, not confirmed +8 = 68 (new).
    23 Marisa live meeting Jun 15, 144 days, 30 x 144 / 91.25 = 47 capped at 40; importance 2
              +10; not confirmed +8 = 58 (follow-up).
    25 Priya  tried Nov 3 (3 days ago: out of the cool-off): never reached after 1 try +40 +5;
              not confirmed +8 = 53 (new).
    30 Hal    maintenance followed up Aug 20: not due until Dec 18, left out.
    -> 31, 21, 27, 23, 25: five tasks.
  Blair (2) owns 22, 24, 26, 28, 33: none ever reached (26's text and 28's email are not live
    talks or tries), none confirmed: 40 + 8 = 48 each, new, ties by id. The rollover snoozes 304.
    -> 22, 24, 26, 28, 33: five tasks.
  Gale (7) is a turned-off salesperson: no batch. Nobody else is a salesperson.
"""
from __future__ import annotations

import time

import pytest

from bd import appsettings, config, ledger, weekly
from bd import weekly_worker

AVERY, BLAIR, EMERY = 1, 2, 5
AVERYS_LIST = [31, 21, 27, 23, 25]
BLAIRS_LIST = [22, 24, 26, 28, 33]
FRIDAY_16 = "2026-11-06T16:00:00-06:00"


def _wait_ticks(worker, n, timeout=30.0):
    deadline = time.monotonic() + timeout
    start = worker.ticks
    while worker.ticks < start + n:
        assert worker.running, "the worker thread died"
        assert time.monotonic() < deadline, "the worker did not tick %d times in %ss" % (n, timeout)
        time.sleep(0.02)


def _batches(db, week):
    """The live Friday batches of `week`: (owner, [contact ids in list order], generated_at)."""
    rows = db.execute(
        "select b.owner_id, b.generated_at, array_agg(t.contact_id order by t.id)"
        " filter (where t.id is not null) as contacts from bd.task_batches b"
        " left join bd.tasks t on t.batch_id = b.id where b.kind = 'friday' and b.week_start = %s"
        " and b.replaced_at is null group by b.id order by b.owner_id", (week,)).fetchall()
    return [(r["owner_id"], r["contacts"] or [], r["generated_at"]) for r in rows]


def _lists(db, week="2026-11-09"):
    return [(owner, contacts) for owner, contacts, _ in _batches(db, week)]


@pytest.fixture
def switched_on(monkeypatch):
    """BD and its Friday batch switched on, as in prod after cut-over."""
    monkeypatch.setattr(config, "BD_ENABLED", True)
    monkeypatch.setattr(config, "BD_WEEKLY_ENABLED", True)


@pytest.fixture
def pin_clock(monkeypatch, bd_today):
    """pin_clock("2026-11-06T16:00:00-06:00"): the business clock (BD_NOW) at that moment, BD_TODAY
    cleared so today follows it, and the open test connections told."""
    def pin(moment):
        monkeypatch.setenv("BD_NOW", moment)
        bd_today(None)
        return moment

    yield pin
    monkeypatch.delenv("BD_NOW", raising=False)


@pytest.fixture
def friday(bd_seeded, pin_clock, switched_on):
    """The fixture seed on Friday 6 Nov 2026 at 16:00 Central."""
    pin_clock(FRIDAY_16)
    return bd_seeded


@pytest.fixture
def stop_worker():
    yield
    weekly_worker.stop()


# ── the switch ───────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bd, weekly_flag, on", [
    (None, None, False),            # both unset: off
    ("on", None, False),            # BD on, the Friday batch unset: off
    ("on", "on", True),
    ("on", "off", False),
    (None, "on", False),            # the batch on but BD off: BD touches no database
    ("off", "on", False),
])
def test_it_runs_only_with_bd_weekly_enabled_on(monkeypatch, bd, weekly_flag, on):
    for name, value in (("BD_ENABLED", bd), ("BD_WEEKLY_ENABLED", weekly_flag)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    config.reload()
    try:
        assert weekly_worker.enabled() is on
    finally:
        monkeypatch.undo()
        config.reload()


def test_bd_weekly_enabled_is_off_when_unset(monkeypatch):
    monkeypatch.delenv("BD_WEEKLY_ENABLED", raising=False)
    monkeypatch.setenv("BD_ENABLED", "on")
    config.reload()
    try:
        assert config.BD_WEEKLY_ENABLED is False
        assert weekly_worker.enabled() is False
    finally:
        monkeypatch.undo()
        config.reload()


def test_switched_off_a_tick_never_opens_the_database(monkeypatch):
    monkeypatch.setattr(config, "BD_ENABLED", True)
    monkeypatch.setattr(config, "BD_WEEKLY_ENABLED", False)

    def no_db(*a, **kw):
        raise AssertionError("a switched-off tick checked out a connection")

    monkeypatch.setattr(weekly_worker.db, "connect", no_db)
    w = weekly_worker.Worker(interval=60, clock=lambda: FRIDAY_16)
    assert w.tick() == [] and w.failures == 0 and w.ticks == 1


# ── never under pytest; the startup hook ─────────────────────────────────────────────────────
def test_the_worker_never_starts_under_pytest(switched_on):
    assert weekly_worker.ensure_started() is False
    assert weekly_worker.current() is None


def test_ensure_started_starts_one_worker_outside_pytest(monkeypatch, switched_on):
    started = []
    monkeypatch.setattr(weekly_worker, "_under_pytest", lambda: False)
    monkeypatch.setattr(weekly_worker, "start", lambda **kw: started.append(kw) or object())
    assert weekly_worker.ensure_started() is True
    assert started == [{"boot_delay": weekly_worker.BOOT_DELAY_S}]


def test_ensure_started_leaves_it_off_when_switched_off(monkeypatch):
    monkeypatch.setattr(config, "BD_ENABLED", True)
    monkeypatch.setattr(config, "BD_WEEKLY_ENABLED", False)
    monkeypatch.setattr(weekly_worker, "_under_pytest", lambda: False)
    monkeypatch.setattr(weekly_worker, "start",
                        lambda **kw: pytest.fail("started while BD_WEEKLY_ENABLED is off"))
    assert weekly_worker.ensure_started() is False


def test_ensure_started_never_raises(monkeypatch, caplog, switched_on):
    def boom(**kw):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(weekly_worker, "_under_pytest", lambda: False)
    monkeypatch.setattr(weekly_worker, "start", boom)
    with caplog.at_level("WARNING", logger="bd.weekly"):
        assert weekly_worker.ensure_started() is False
    assert "weekly worker failed to start (RuntimeError)" in caplog.text


def test_the_startup_hook_starts_the_worker(monkeypatch):
    import main

    calls = []
    monkeypatch.setattr(weekly_worker, "ensure_started", lambda: calls.append(True) or True)
    main._start_bd_weekly()
    assert calls == [True]
    assert main._start_bd_weekly in main.app.router.on_startup


def test_the_tools_other_startup_hooks_still_run(monkeypatch):
    """Starting the app runs every startup hook, the BD worker's and the tool's own (a lifespan
    would have stopped them). Each hook's work is replaced by a note, so nothing really starts."""
    from fastapi.testclient import TestClient

    import main

    ran = []

    def note(name, value=None):
        return lambda *a, **kw: ran.append(name) or value

    monkeypatch.setattr(main.proposal_fonts, "report_once", note("proposal font"))
    monkeypatch.setattr(main.drafts, "init_db", note("drafts"))
    monkeypatch.setattr(main.digest_worker, "set_hooks", note("digest hooks"))
    monkeypatch.setattr(main.digest_worker, "ensure_started", note("digest"))
    monkeypatch.setattr(main.pva_refresh_worker, "ensure_started", note("pva refresh"))
    monkeypatch.setattr(main.basisboard_client, "ensure_refresher_started", note("basisboard"))
    monkeypatch.setattr(main, "_warm_all_sheets", note("sheet warm-up"))
    monkeypatch.setattr(weekly_worker, "ensure_started", note("bd weekly"))
    with TestClient(main.app):
        deadline = time.monotonic() + 10
        while "sheet warm-up" not in ran and time.monotonic() < deadline:   # its own thread
            time.sleep(0.01)
    assert sorted(ran) == sorted(["proposal font", "drafts", "digest hooks", "digest", "pva refresh",
                                  "basisboard", "sheet warm-up", "bd weekly"])


# ── the Friday run on the fixture seed ───────────────────────────────────────────────────────
def test_at_friday_16_one_batch_per_salesperson_and_none_after_a_restart(friday, bd_db, stop_worker):
    w = weekly_worker.start(interval=0.02)
    _wait_ticks(w, 3)
    weekly_worker.stop()
    assert not w.running and w.failures == 0
    assert _lists(bd_db) == [(AVERY, AVERYS_LIST), (BLAIR, BLAIRS_LIST)]
    # Built at the pinned moment, 16:00 CST = 22:00 UTC.
    assert {b[2].isoformat() for b in _batches(bd_db, "2026-11-09")} == {"2026-11-06T22:00:00+00:00"}
    assert [(b["owner_id"], b["tasks_created"], str(b["week_start"])) for b in w.built] == [
        (AVERY, 5, "2026-11-09"), (BLAIR, 5, "2026-11-09")]
    # The rollover closed last week's open tasks: 301, 302 (Avery) and 304 (Blair).
    rows = bd_db.execute("select id, status, snoozed_until from bd.tasks where id between 301 and 305"
                         " order by id").fetchall()
    assert [(r["id"], r["status"], str(r["snoozed_until"])) for r in rows] == [
        (301, "snoozed", "2026-11-09"), (302, "snoozed", "2026-11-09"), (303, "done", "None"),
        (304, "snoozed", "2026-11-09"), (305, "snoozed", "2026-11-10")]

    # The app restarts later the same evening (a new worker): nothing more is built.
    w2 = weekly_worker.start(interval=0.02)
    assert w2 is not w
    _wait_ticks(w2, 3)
    weekly_worker.stop()
    assert w2.built == [] and w2.failures == 0
    assert _lists(bd_db) == [(AVERY, AVERYS_LIST), (BLAIR, BLAIRS_LIST)]


def test_one_worker_per_process(friday, stop_worker):
    w = weekly_worker.start(interval=0.02)
    assert weekly_worker.start(interval=0.02) is w and weekly_worker.current() is w


def test_the_default_clock_is_the_business_clock(pin_clock):
    """Never the machine's clock (the dev box runs ~13 hours ahead of Central)."""
    pin_clock("2026-11-06T15:59:59-06:00")
    assert weekly_worker.Worker().clock().isoformat() == "2026-11-06T15:59:59-06:00"


# Run day (settings.weekly.run_day, at the default hour 16), the pinned Central moment, and the
# Monday a batch is built for (None: nothing is built). Fri 6, Sat 7 and Sun 8 Nov 2026 are all
# CST (UTC-6); the Monday after is the 9th.
RUN_CLOCK = [
    ("friday", "2026-11-06T15:59:59-06:00", None),                 # before the hour
    ("friday", "2026-11-06T16:00:00-06:00", "2026-11-09"),         # at it
    ("friday", "2026-11-06T17:30:00-06:00", "2026-11-09"),         # after it
    ("friday", "2026-11-06T21:59:59Z", None),                      # 15:59:59 CST, given in UTC
    ("friday", "2026-11-06T22:00:00Z", "2026-11-09"),              # 16:00 CST, given in UTC
    ("friday", "2026-11-07T09:00:00-06:00", "2026-11-09"),         # down on Friday: Saturday catches up
    ("friday", "2026-11-08T23:00:00-06:00", "2026-11-09"),         # or Sunday
    ("friday", "2026-11-05T16:00:00-06:00", None),                 # Thursday at the hour
    ("friday", "2026-11-09T16:00:00-06:00", None),                 # Monday: a new week, not due
    ("saturday", "2026-11-06T16:00:00-06:00", None),               # Friday is not the run day
    ("saturday", "2026-11-07T15:59:59-06:00", None),
    ("saturday", "2026-11-07T16:00:00-06:00", "2026-11-09"),
    ("saturday", "2026-11-07T20:00:00-06:00", "2026-11-09"),
    ("sunday", "2026-11-07T16:00:00-06:00", None),
    ("sunday", "2026-11-08T15:59:59-06:00", None),
    ("sunday", "2026-11-08T16:00:00-06:00", "2026-11-09"),
    ("sunday", "2026-11-08T23:59:59-06:00", "2026-11-09"),
]


@pytest.mark.parametrize("run_day, moment, week", RUN_CLOCK,
                         ids=["%s@%s" % (d, m) for d, m, _ in RUN_CLOCK])
def test_the_run_day_and_hour_in_central_time(bd_seeded, bd_db, pin_clock, switched_on, run_day, moment, week):
    appsettings.store(bd_db, {"weekly": {"run_day": run_day, "run_hour": 16}})
    pin_clock(moment)
    w = weekly_worker.Worker(interval=60)
    built = w.tick()
    assert w.failures == 0
    if week is None:
        assert built == [] and _lists(bd_db, "2026-11-09") == [] and _lists(bd_db, "2026-11-16") == []
    else:
        assert [(b["owner_id"], str(b["week_start"])) for b in built] == [(AVERY, week), (BLAIR, week)]
        assert [owner for owner, _ in _lists(bd_db, week)] == [AVERY, BLAIR]
        assert w.tick() == []                              # the next tick: already built


def test_the_run_hour_comes_from_bd_settings(friday, bd_db):
    """An admin moved the run to 18:00: 16:00 and 17:59 build nothing, 18:00 builds."""
    appsettings.store(bd_db, {"weekly": {"run_hour": 18}})
    w = weekly_worker.Worker(interval=60, clock=lambda: "2026-11-06T17:59:59-06:00")
    assert w.tick() == [] and _lists(bd_db) == []
    w.clock = lambda: "2026-11-06T18:00:00-06:00"
    assert [b["owner_id"] for b in w.tick()] == [AVERY, BLAIR]


def test_switched_off_in_settings_builds_nothing(friday, bd_db, stop_worker):
    appsettings.store(bd_db, {"weekly": {"enabled": False}})
    w = weekly_worker.start(interval=0.02)
    _wait_ticks(w, 3)
    weekly_worker.stop()
    assert w.built == [] and _lists(bd_db) == []


def test_an_admin_run_first_means_the_worker_skips_that_owner(friday, bd_db, bd_as_user, stop_worker):
    r = bd_as_user(EMERY).post("/api/bd/admin/weekly/run", json={"owner": AVERY})
    assert r.status_code == 200, r.text
    w = weekly_worker.start(interval=0.02)
    _wait_ticks(w, 3)
    weekly_worker.stop()
    assert [b["owner_id"] for b in w.built] == [BLAIR]
    assert [owner for owner, _ in _lists(bd_db)] == [AVERY, BLAIR]


def test_a_database_behind_the_code_builds_nothing(friday, bd_db, monkeypatch, caplog):
    """The routes answer "database not up to date" then; the worker builds nothing either."""
    monkeypatch.setattr(ledger, "ledger_behind", lambda conn: True)
    w = weekly_worker.Worker(interval=60)
    with caplog.at_level("WARNING", logger="bd.weekly"):
        assert w.tick() == []
    assert _lists(bd_db) == [] and w.failures == 0
    assert "database is not up to date" in caplog.text


def test_a_failing_tick_is_logged_and_the_worker_keeps_going(friday, monkeypatch, caplog, stop_worker):
    def boom(conn, now=None, **kw):
        raise RuntimeError("the database went away")

    monkeypatch.setattr(weekly, "run_due", boom)
    with caplog.at_level("ERROR", logger="bd.weekly"):
        w = weekly_worker.start(interval=0.02)
        _wait_ticks(w, 3)
        assert w.running
        weekly_worker.stop()
    assert w.failures >= 3
    assert "weekly worker tick failed" in caplog.text


def test_one_owner_failing_never_costs_the_others_their_list(friday, bd_db, monkeypatch, caplog):
    real = weekly.build_batch

    def flaky(conn, owner, *a, **kw):
        if weekly._owner_id(owner) == BLAIR:
            raise RuntimeError("Blair's build failed")
        return real(conn, owner, *a, **kw)

    monkeypatch.setattr(weekly, "build_batch", flaky)
    w = weekly_worker.Worker(interval=60)
    with caplog.at_level("ERROR", logger="bd.weekly"):
        assert [b["owner_id"] for b in w.tick()] == [AVERY]
        assert w.tick() == []                         # Avery is done; Blair fails again
    assert w.failures == 2 and w.ticks == 2
    assert "owner %s" % BLAIR in caplog.text
    assert _lists(bd_db) == [(AVERY, AVERYS_LIST)]
    monkeypatch.setattr(weekly, "build_batch", real)
    assert [b["owner_id"] for b in w.tick()] == [BLAIR]
    assert _lists(bd_db) == [(AVERY, AVERYS_LIST), (BLAIR, BLAIRS_LIST)]


def test_the_worker_never_calls_the_model_or_the_machine_clock():
    import pathlib

    src = pathlib.Path(weekly_worker.__file__).read_text(encoding="utf-8").lower()
    for word in ("subprocess", "claude", "anthropic", "datetime.now(", "date.today(", "time.time("):
        assert word not in src, word


# ── staging never builds batches on its own ──────────────────────────────────────────────────
def test_staging_keeps_the_friday_batch_off_and_prod_leaves_it_unset():
    """The ticket's one-way step: BD_WEEKLY_ENABLED=off inline in the staging compose file. Prod's
    compose file does not set it (off) until cut-over day."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2]
    staging = (root / "docker-compose.staging.yml").read_text(encoding="utf-8")
    prod = (root / "docker-compose.yml").read_text(encoding="utf-8")
    assert [line.strip() for line in staging.splitlines()].count("- BD_WEEKLY_ENABLED=off") == 1
    assert "BD_WEEKLY_ENABLED" not in prod
