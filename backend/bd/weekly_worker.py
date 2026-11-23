"""The Friday worker: a background thread that builds each salesperson's weekly 10 when it is due.

Ported from BD's weekly_worker.py (#807). BD started it from its app's lifespan; inside the
proposal tool it is built like the tool's other workers (backend/pva_refresh_worker.py,
backend/digest_worker.py):

  * STARTED FROM A STARTUP HOOK (main._start_bd_weekly calls ensure_started()), never from a
    lifespan: passing a lifespan to the tool's app would stop its other startup hooks running.
  * ensure_started() NEVER RAISES, and never starts a thread under pytest (the tests start a Worker
    themselves, or call tick() directly).
  * A MODULE LOCK keeps it to one worker per process. The image runs one uvicorn worker.
  * It runs only when BD_WEEKLY_ENABLED is on (default off), and BD itself is on (BD_ENABLED):
    with the BD switch off, BD touches no database. Prod turns both on at cut-over; staging keeps
    BD_WEEKLY_ENABLED off, so staging never builds batches on its own (an admin runs one by hand).

Every INTERVAL seconds (60) a tick checks out one pooled connection (bd/db.py) and calls

    weekly.run_due(conn, bizdate.now_central(), commit=True, failed=[...])

which reads settings.weekly (enabled, run_day, run_hour) and asks weekly.should_run for every
active salesperson: due once the run moment of the current Central week has passed (Friday 16:00
by default, for next week; a worker that was down catches up on Saturday or Sunday). The day and
hour are always America/Chicago: "now" is bizdate's business clock, never the machine's (the dev
box runs ~13 hours ahead of Central; BD_NOW / BD_TODAY pin it in tests). The unique index of
migrations/003_one_friday_batch.sql and weekly.build_batch's per-owner advisory lock make a
second build of the same week impossible: an owner who already has one (an admin ran it, another
process got there first) is skipped. So restarting the app, or a tick that overlaps an admin's
run, never makes a second batch.

A database behind the code (the migrations ledger, bd/ledger.py) builds nothing: the routes
answer "database not up to date" then, and so does the worker, in its log.

NOT AI: nothing here or in weekly.py calls the model.

FAILURES never reach the app: a tick that raises (the database is down, a bad setting) is logged
and the next tick tries again. One owner whose build fails costs nobody else their list: run_due
builds and commits each owner on its own, logs the failed one by id and goes on, and the tick
counts it in `failures`. Plain logging on the "bd.weekly" logger.
"""
from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from typing import Any

from . import bizdate, config, db, ledger, weekly

log = logging.getLogger("bd.weekly")

INTERVAL = 60.0          # seconds between ticks
BOOT_DELAY_S = 30.0      # ensure_started(): let start-up finish before the first look

_lock = threading.Lock()
_current: Worker | None = None


def enabled() -> bool:
    """BD_WEEKLY_ENABLED on, with the BD switch on. Both default off."""
    return bool(config.BD_ENABLED) and bool(config.BD_WEEKLY_ENABLED)


def _under_pytest() -> bool:
    return "pytest" in sys.modules


class Worker:
    """One daemon thread. `clock` returns the moment to judge "due" by (default
    bizdate.now_central); `interval` is the wait between ticks; `boot_delay` the wait before the
    first one."""

    def __init__(self, interval: float = INTERVAL, clock: Callable[[], Any] | None = None,
                 boot_delay: float = 0.0):
        self.interval = float(interval)
        self.clock = clock or bizdate.now_central
        self.boot_delay = float(boot_delay)
        self.ticks = 0                   # finished ticks, failed ones included
        self.failures = 0                # failed ticks plus failed owner builds
        self.built: list = []            # every batch this worker built: run_due's rows
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> Worker:
        if self.running:
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="bd-weekly-worker", daemon=True)
        self._thread.start()
        log.info("weekly worker started (every %ss)", self.interval)
        return self

    def stop(self, timeout: float = 30.0) -> None:
        self._stop.set()
        t = self._thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout)
            if t.is_alive():
                log.warning("weekly worker did not stop within %ss", timeout)
        self._thread = None
        log.info("weekly worker stopped")

    def tick(self) -> list:
        """One look: build what is due. Returns run_due's rows ([] when switched off, nothing was
        due, the database is behind the code, or the tick failed). Never raises."""
        try:
            if not enabled():
                return []
            now = self.clock()
            failed: list = []
            with db.connect() as conn:
                if ledger.ledger_behind(conn):
                    log.warning("weekly worker: BD's database is not up to date; building nothing")
                    return []
                built = weekly.run_due(conn, now, commit=True, failed=failed)
            self.failures += len(failed)
            for b in built:
                log.info("weekly batch built: owner %s, week of %s, batch %s, %s tasks",
                         b["owner_id"], b["week_start"], b["batch_id"], b["tasks_created"])
            self.built.extend(built)
            return built
        except Exception:  # the worker must never take the app down
            self.failures += 1
            log.exception("weekly worker tick failed; trying again in %ss", self.interval)
            return []
        finally:
            self.ticks += 1

    def _loop(self) -> None:
        if self.boot_delay > 0 and self._stop.wait(self.boot_delay):
            return
        while not self._stop.is_set():
            self.tick()
            self._stop.wait(self.interval)


def start(interval: float = INTERVAL, clock: Callable[[], Any] | None = None,
          boot_delay: float = 0.0) -> Worker:
    """Start this process's worker (or return the one already running)."""
    global _current
    with _lock:
        if _current is not None and _current.running:
            return _current
        _current = Worker(interval, clock, boot_delay).start()
        return _current


def stop(timeout: float = 30.0) -> None:
    """Stop this process's worker, if one is running."""
    global _current
    with _lock:
        w, _current = _current, None
    if w is not None:
        w.stop(timeout)


def current() -> Worker | None:
    return _current


def ensure_started() -> bool:
    """Start the worker, once, from the app's startup hook. False under pytest, when switched off,
    or when it could not start. Never raises: a batch that cannot start must not take the tool
    down with it."""
    if _under_pytest() or not enabled():
        return False
    try:
        start(boot_delay=BOOT_DELAY_S)
    except Exception as exc:  # noqa: BLE001
        log.warning("weekly worker failed to start (%s)", type(exc).__name__)
        return False
    log.info("BD weekly worker on (run day and hour from BD settings, Central time)")
    return True
