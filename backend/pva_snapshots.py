"""Plan vs Actual snapshots (#784): one row per listed row (a Project, or its Punch) per Central
day, after a good run.

After every GOOD refresh (the 5:00 AM daily run or "Refresh now": the calendar read without an
error or a stale copy, and Raken read and kept), plan_vs_actual hands its listed rows to write(),
which keeps each row's figures in the `pva_snapshots` table of the data store, so
trends can be shown later (showing them is not part of #784). The words are GLOSSARY.md's.

  pva_snapshots (project_key text, snap_date date, figures jsonb, ran_at timestamptz,
                 primary key (project_key, snap_date))

  * project_key is the row's own key ("job:<Job number>", "name:<name>", "punch:..."), the one the
    page and the list already use.
  * snap_date is the day in Central the run belongs to; a second good run that day REPLACES the row
    (an upsert on the primary key), so a day keeps its last good figures.
  * ran_at is when Raken was read (raken_actuals' "as of", Central with its offset).
  * figures are the row's computed figures, the plan and the Raken side with its statuses: never the
    day-by-day, the Mobilizations, or the Raken projects' names.

The DDL is backend/ops/pva_snapshots.sql (also in supabase_schema.sql and staging/schema_pg.sql),
applied by hand on each database. Until it is, write() logs one fixed line, once, and the page
carries on as before: a snapshot is never worth a failed refresh or a 500. Never raises.

Logs carry literal text and counts only, never anything read from Raken, Google or the store
(CodeQL py/clear-text-logging-sensitive-data).
"""
from __future__ import annotations

import datetime as _dt
import logging
import threading
from typing import Any, Dict, Iterable, List, Optional

from supabase_client import get_client, table_missing

log = logging.getLogger("treadwell.pva_snapshots")

TABLE = "pva_snapshots"
ON_CONFLICT = "project_key,snap_date"

# A row's figures that a snapshot keeps, and of its Raken side the same.
ROW_FIGURES = ("job_number", "name", "is_punch", "work_type", "foreman", "start", "deadline",
               "timing", "workdays_left", "workdays_so_far", "crew_size", "planned_hours",
               "crew_size_missing", "statuses")
RAKEN_FIGURES = ("state", "reason", "days_booked", "days_clocked", "avg_on_site", "actual_hours",
                 "last_week_hours", "budget", "budgeted_hours", "projected_total_hours",
                 "over_under", "projection_below_actual", "through")

_LOCK = threading.Lock()
_MISSING_LOGGED = {"done": False}


def figures(row: Dict[str, Any]) -> Dict[str, Any]:
    """The figures one snapshot keeps for one listed row."""
    out = {k: row.get(k) for k in ROW_FIGURES}
    side = row.get("raken") if isinstance(row.get("raken"), dict) else {}
    out["raken"] = {k: side[k] for k in RAKEN_FIGURES if k in side}
    return out


def rows_for(projects: Iterable[Dict[str, Any]], snap_date: _dt.date,
             ran_at: Optional[str]) -> List[Dict[str, Any]]:
    """One snapshot row per listed Project with a key (the last one wins should two share it)."""
    by_key: Dict[str, Dict[str, Any]] = {}
    for p in projects:
        key = p.get("key") if isinstance(p, dict) else None
        if isinstance(key, str) and key:
            by_key[key] = {"project_key": key, "snap_date": snap_date.isoformat(),
                           "figures": figures(p), "ran_at": ran_at}
    return list(by_key.values())


def write(projects: Iterable[Dict[str, Any]], snap_date: _dt.date, ran_at: Optional[str]) -> int:
    """Keep today's snapshot of every listed Project, replacing any kept earlier the same day.
    Answers how many rows were written (0 when none could be). Never raises."""
    batch = rows_for(projects, snap_date, ran_at)
    if not batch:
        return 0
    try:
        get_client().table(TABLE).upsert(batch, on_conflict=ON_CONFLICT).execute()
    except Exception as exc:  # noqa: BLE001 - a snapshot never fails the refresh
        if table_missing(exc):
            with _LOCK:
                first = not _MISSING_LOGGED["done"]
                _MISSING_LOGGED["done"] = True
            if first:
                log.warning("pva snapshots: the pva_snapshots table is not on this database yet "
                            "(backend/ops/pva_snapshots.sql); no snapshots are kept until it is")
            return 0
        log.warning("pva snapshots: %d row(s) not kept (%s)", len(batch), type(exc).__name__)
        return 0
    log.info("pva snapshots: kept %d row(s)", len(batch))
    return len(batch)


def reset_for_tests() -> None:
    with _LOCK:
        _MISSING_LOGGED["done"] = False
