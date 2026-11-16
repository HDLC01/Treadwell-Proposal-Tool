"""Plan vs Actual, the daily refresh (#784): at 5:00 AM Central, the "Refresh now" step by itself.

One daemon thread. Once a day, from 5:00 AM Central, it calls plan_vs_actual.refresh(), the very
step "Refresh now" runs: it reads the Treadwell Projects calendar and Raken, keeps the read on the
data volume (raken_actuals.json), and after a good read keeps one snapshot of each listed Project's
figures (backend/pva_snapshots.py). The words are GLOSSARY.md's.

BUILT LIKE THE 6 AM DIGEST (backend/digest_worker.py), for the same reasons:
  * STARTED FROM A STARTUP HOOK, never lazily on a first request: nobody opens a page at 5 AM, so a
    lazy start would read Raken only once somebody signed in.
  * AT MOST ONCE A DAY. `last_run` in pva_refresh_state.json, on the same Docker volume as the
    drafts DB, is the whole idempotency story: a container restarted at 7:15 still runs that day
    (5:00 has passed and today is not stamped), and one restarted at 5:05 having already run does
    not. The day is stamped BEFORE the run: a run that fails (a 429 that persisted, the daily Raken
    quota used up, Raken or Google down) is not tried again every few minutes, which would only
    spend more of the company's shared Raken allowance. The last good numbers stay on the page with
    their "as of" time, and "Refresh now" is still there.
  * NEVER A THREAD UNDER PYTEST. The tests call should_run() and run_once() directly.

5:00 AM IS CENTRAL'S, worked out with zoneinfo from a UTC instant, never from the machine's clock
(the dev box runs ~13 hours ahead of Central), so both daylight-saving changes land on the right hour.

A RUN ALREADY GOING IS WAITED FOR, NOT DOUBLED. A "Refresh now" pressed just before 5:00 holds
plan_vs_actual's one refresh lock; the daily run waits for it to finish and takes its outcome
instead of reading Raken a second time (plan_vs_actual.refresh(wait=True)). A "Refresh now" pressed
while the daily run is going answers at once saying a refresh is running, and the page polls until
it is done, exactly as for two presses.

  PVA_REFRESH_ENABLED  on | off   (default ON: it only reads Raken and the calendar, and writes
                                   nothing outside the tool)

Circular imports: this module never imports main; main starts it from a startup hook.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import atomic_json

log = logging.getLogger("treadwell.pva_refresh_worker")

try:                                        # py3.9+ stdlib; matches the rest of the app
    from zoneinfo import ZoneInfo
except ImportError:                         # pragma: no cover
    ZoneInfo = None  # type: ignore

BIZ_TZ = "America/Chicago"
RUN_HOUR = 5                                # 5:00 AM Central

_DATA_DIR = Path(os.environ.get("DRAFTS_DB_PATH", "/app/data/drafts.db")).parent
_STATE_FILE = _DATA_DIR / "pva_refresh_state.json"
_MEM_STATE: Dict[str, Any] = {}             # fallback when the volume is not writable

_TICK_S = 300                               # 5 min: the hour boundary is the trigger
_BOOT_DELAY_S = 30                          # let startup finish before the first look

_START_LOCK = threading.Lock()
_THREAD: Optional[threading.Thread] = None


# ── config ────────────────────────────────────────────────────────────────────
def enabled() -> bool:
    """ON unless switched off. The run reads Raken and the calendar and writes only the tool's own
    files and snapshot rows, so being on by mistake costs one read of the company's Raken allowance
    a day, and being off by mistake leaves the numbers a day old."""
    return (os.environ.get("PVA_REFRESH_ENABLED") or "on").strip().lower() not in (
        "off", "0", "false", "no")


# ── time ──────────────────────────────────────────────────────────────────────
def _biz_tz():
    return ZoneInfo(BIZ_TZ) if ZoneInfo else timezone.utc


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def biz_now(now: Optional[datetime] = None) -> datetime:
    return (now or now_utc()).astimezone(_biz_tz())


# ── state ─────────────────────────────────────────────────────────────────────
def load_state() -> Dict[str, Any]:
    try:
        if _STATE_FILE.is_file():
            data = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception as exc:  # noqa: BLE001 - a garbled file must not stop the run
        log.warning("pva refresh: the day stamp is unreadable (%s)", type(exc).__name__)
    return dict(_MEM_STATE)


def save_state(state: Dict[str, Any]) -> None:
    global _MEM_STATE
    _MEM_STATE = dict(state)                 # the in-process copy is always current
    try:
        if _DATA_DIR.is_dir() and os.access(_DATA_DIR, os.W_OK):
            atomic_json.write_json(_STATE_FILE, state, make_parent=False)
    except Exception as exc:  # noqa: BLE001
        log.warning("pva refresh: the day stamp could not be saved (%s)", type(exc).__name__)


def should_run(state: Dict[str, Any], now: Optional[datetime] = None) -> bool:
    """Has 5:00 AM Central passed today, and today's run not happened?

    "Has passed" rather than "is now": a container down at 5:00 and back at 7:15 still runs the
    morning's refresh. It is late, not void."""
    b = biz_now(now)
    if b.hour < RUN_HOUR:
        return False
    return str(state.get("last_run") or "") != b.date().isoformat()


# ── one run ───────────────────────────────────────────────────────────────────
def run_once(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Stamp today, then run the "Refresh now" step, waiting for one already going. Answers what
    plan_vs_actual.refresh() answers. The stamp goes first so a run that fails or crashes is not
    retried every tick (see the module docstring)."""
    import plan_vs_actual                   # here, not at the top: it imports the calendar stack
    state = load_state()
    state["last_run"] = biz_now(now).date().isoformat()
    save_state(state)
    body = plan_vs_actual.refresh(wait=True)
    raken = body.get("raken") or {}
    # Literal text and counts only: nothing read from Raken or Google reaches the log.
    log.info("pva refresh: daily run done, %d project(s) listed, Raken numbers %s",
             len(body.get("projects") or []),
             "kept from an earlier read" if raken.get("stale") else "as read")
    return body


# ── the thread ────────────────────────────────────────────────────────────────
def _tick(now: Optional[datetime] = None) -> None:
    if not enabled():
        return
    if not should_run(load_state(), now):
        return
    run_once(now)


def _run() -> None:
    time.sleep(_BOOT_DELAY_S)
    while True:
        try:
            _tick()
        except Exception as exc:  # noqa: BLE001 - the loop outlives every failure
            log.warning("pva refresh: tick failed (%s)", type(exc).__name__)
        time.sleep(_TICK_S)


def ensure_started() -> bool:
    """Start the daily thread, once, from the app's startup hook. Never raises: a refresh that
    cannot start must not take the app down with it."""
    global _THREAD
    import sys
    # Under pytest a background thread reaching for Google and Raken would race every test that
    # fakes them. The tests call should_run(), _tick() and run_once() directly.
    if "pytest" in sys.modules or not enabled():
        return False
    if _THREAD is not None and _THREAD.is_alive():
        return True
    try:
        with _START_LOCK:
            if _THREAD is not None and _THREAD.is_alive():
                return True
            _THREAD = threading.Thread(target=_run, name="pva-refresh", daemon=True)
            _THREAD.start()
        log.info("Plan vs Actual daily refresh started (%d:00 %s)", RUN_HOUR, BIZ_TZ)
        return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Plan vs Actual daily refresh failed to start (%s)", type(exc).__name__)
        return False
