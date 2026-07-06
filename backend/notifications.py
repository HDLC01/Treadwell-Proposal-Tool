"""In-app notification-bell feed.

Two sources, no schema change:

  1. Proposal DEADLINES — computed live from the active drafts (overdue / due
     today / due soon / no deadline set), bucketed in Treadwell's business
     timezone (Central) so they match the dates shown on the cards.

  2. Basisboard PIPELINE changes — bid awarded / stage moved / new bid. Basisboard
     is read-only with NO webhook, so we snapshot the pipeline and DIFF it against
     the previous snapshot on each refresh to detect what changed.

State is GLOBAL/shared (per the product decision — one last-seen for the whole
team) and lives in a small JSON file on the persistent /app/data volume (the same
volume as the drafts DB — see docker-compose + audit.py). It holds the last-seen
marker, the pipeline snapshot, and the recently-detected pipeline changes. If the
volume isn't writable (local dev / tests) it degrades to an in-process dict.

Everything is best-effort: an unconfigured Basisboard, a missing volume, or a bad
read never raises — the bell just shows fewer items. Emails are unaffected.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import basisboard_client
import drafts as drafts_mod

log = logging.getLogger("proposal_tool.notifications")

# Persistent state file on the same volume as the drafts DB (audit.py convention).
_DB_PATH = os.environ.get("DRAFTS_DB_PATH") or "/app/data/drafts.db"
DATA_DIR = Path(_DB_PATH).parent
_STATE_FILE = DATA_DIR / "notif_state.json"

_LOCK = threading.Lock()
_MEM_STATE: Dict[str, Any] = {}        # fallback when the volume isn't writable
_PIPELINE_TTL_S = 55                   # don't re-diff Basisboard more often than this
_PIPELINE_KEEP_DAYS = 30               # prune pipeline change events older than this
_MAX_ITEMS = 60
_TZ_NAME = "America/Chicago"
_EPOCH = "1970-01-01T00:00:00+00:00"


# ── time helpers ──────────────────────────────────────────────────────
def _biz_tz():
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(_TZ_NAME)
    except Exception:                  # pragma: no cover - tzdata missing
        return timezone.utc


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def _biz_today():
    return _now().astimezone(_biz_tz()).date()


def _date_iso(d) -> str:
    """Midnight (UTC) ISO for a date — a stable, comparable timestamp for a
    deadline-derived notification."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc).isoformat()


# ── state (JSON on the volume, in-memory fallback) ─────────────────────
def _load_state() -> Dict[str, Any]:
    try:
        if _STATE_FILE.is_file():
            return json.loads(_STATE_FILE.read_text(encoding="utf-8")) or {}
    except Exception as exc:           # noqa: BLE001
        log.warning("notif state read failed: %s", exc)
    return dict(_MEM_STATE)


def _save_state(state: Dict[str, Any]) -> None:
    global _MEM_STATE
    _MEM_STATE = dict(state)            # always keep the in-process copy fresh
    try:
        if DATA_DIR.is_dir() and os.access(DATA_DIR, os.W_OK):
            tmp = _STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(state), encoding="utf-8")
            tmp.replace(_STATE_FILE)   # atomic
    except Exception as exc:           # noqa: BLE001
        log.warning("notif state write failed: %s", exc)


# ── pipeline snapshot + diff ───────────────────────────────────────────
def _snapshot(projects: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        p["id"]: {
            "stage_id": p.get("stage_id"),
            "stage_name": p.get("stage_name"),
            "awarded": bool(p.get("awarded")),
            "name": p.get("name"),
        }
        for p in projects if p.get("id")
    }


def _diff_pipeline(prev: Dict[str, Any], projects: List[Dict[str, Any]],
                   now_iso: str) -> List[Dict[str, Any]]:
    """Return notification dicts for what changed vs the previous snapshot."""
    changes: List[Dict[str, Any]] = []
    for p in projects:
        pid = p.get("id")
        if not pid:
            continue
        old = prev.get(pid)
        name = p.get("name") or "A bid"
        if old is None:                                     # appeared since last snapshot
            changes.append({
                "id": f"pl:new:{pid}:{now_iso}", "kind": "pipeline_new", "icon": "✨",
                "severity": "info", "sort": 3, "ts": now_iso, "link": "/crm.html",
                "title": name,
                "body": f"New bid in the pipeline · {p.get('stage_name') or 'Unstaged'}",
            })
            continue
        if bool(p.get("awarded")) and not old.get("awarded"):
            changes.append({
                "id": f"pl:award:{pid}:{now_iso}", "kind": "pipeline_awarded", "icon": "🏆",
                "severity": "high", "sort": 3, "ts": now_iso, "link": "/crm.html",
                "title": name, "body": "Bid awarded 🎉",
            })
        elif p.get("stage_id") != old.get("stage_id"):
            frm = old.get("stage_name")
            changes.append({
                "id": f"pl:stage:{pid}:{now_iso}", "kind": "pipeline_stage", "icon": "➡️",
                "severity": "info", "sort": 3, "ts": now_iso, "link": "/crm.html",
                "title": name,
                "body": (f"Moved to {p.get('stage_name') or 'a new stage'}"
                         + (f" (from {frm})" if frm else "")),
            })
    return changes


def _prune_events(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cutoff = (_now() - timedelta(days=_PIPELINE_KEEP_DAYS)).isoformat()
    kept = [e for e in events if (e.get("ts") or "") >= cutoff]
    return kept[-100:]                 # hard cap regardless


def _refresh_pipeline(state: Dict[str, Any]) -> None:
    """Fetch Basisboard (cached 60 s in the client), diff vs the stored snapshot,
    append any changes, and update the snapshot. Throttled + best-effort; mutates
    `state` in place. On the FIRST run (no prior snapshot) it just records the
    baseline and emits nothing (so we don't flood the bell with 'new bid' for the
    entire existing pipeline)."""
    if not basisboard_client.is_configured():
        return
    synced_at = state.get("pipeline_synced_at")
    if synced_at:
        try:
            if (_now() - datetime.fromisoformat(synced_at)).total_seconds() < _PIPELINE_TTL_S:
                return
        except Exception:              # noqa: BLE001 - bad stored value → refresh anyway
            pass
    data = basisboard_client.get_pipeline()
    if not data.get("ok"):
        return
    projects = data.get("projects") or []
    now_iso = _now_iso()
    prev = state.get("pipeline_snapshot")
    if prev:                           # only diff when we already have a baseline
        new_changes = _diff_pipeline(prev, projects, now_iso)
        if new_changes:
            events = list(state.get("pipeline_events") or [])
            events.extend(new_changes)
            state["pipeline_events"] = _prune_events(events)
    state["pipeline_snapshot"] = _snapshot(projects)
    state["pipeline_synced_at"] = now_iso


# ── deadlines ──────────────────────────────────────────────────────────
def _parse_date(s: Optional[str]):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except Exception:                  # noqa: BLE001
        return None


def _deadline_notifications(projects: List[Dict[str, Any]], today) -> List[Dict[str, Any]]:
    """Overdue / due-today / due-soon(≤7d) / no-deadline, for ACTIVE (non-archived)
    projects. `today` is the business-timezone date (injected for testability)."""
    out: List[Dict[str, Any]] = []
    for p in projects:
        if p.get("archived"):          # inactive/finished → don't nag
            continue
        pid = p.get("id")
        name = p.get("project_name") or "(untitled)"
        link = f"/?d={pid}&edit=1"
        dl = _parse_date(p.get("deadline"))
        if dl is None:
            out.append({
                "id": f"dl:none:{pid}", "kind": "deadline_none", "icon": "⚪",
                "severity": "low", "sort": 4,
                "ts": p.get("updated_at") or p.get("created_at") or _EPOCH,
                "title": name, "body": "No deadline set", "link": link,
            })
            continue
        days = (dl - today).days
        dl_str = f"{dl:%b} {dl.day}"
        if days < 0:
            n = abs(days)
            out.append({
                "id": f"dl:overdue:{pid}", "kind": "deadline_overdue", "icon": "🔴",
                "severity": "high", "sort": 0, "ts": _date_iso(dl), "title": name,
                "body": f"Overdue by {n} day{'s' if n != 1 else ''} ({dl_str})", "link": link,
            })
        elif days == 0:
            out.append({
                "id": f"dl:today:{pid}", "kind": "deadline_today", "icon": "🟠",
                "severity": "high", "sort": 1, "ts": _date_iso(dl), "title": name,
                "body": f"Due today ({dl_str})", "link": link,
            })
        elif days <= 7:
            out.append({
                "id": f"dl:soon:{pid}", "kind": "deadline_soon", "icon": "🟡",
                "severity": "medium", "sort": 2, "ts": _date_iso(dl - timedelta(days=7)),
                "title": name,
                "body": f"Due in {days} day{'s' if days != 1 else ''} ({dl_str})", "link": link,
            })
        # days > 7 → not yet noteworthy
    return out


# ── public API ─────────────────────────────────────────────────────────
def get_notifications() -> Dict[str, Any]:
    """Assemble the feed: deadline items (live) + recent pipeline changes, sorted
    by section then newest-first. `unread` counts items newer than the global
    last-seen marker."""
    with _LOCK:
        state = _load_state()
        try:
            _refresh_pipeline(state)
        except Exception as exc:       # noqa: BLE001 - never let the pipeline break the bell
            log.warning("pipeline refresh failed: %s", exc)
        _save_state(state)
        last_seen = state.get("last_seen_at") or _EPOCH

    try:
        projects = drafts_mod.list_drafts()
    except Exception as exc:           # noqa: BLE001
        log.warning("list_drafts for notifications failed: %s", exc)
        projects = []

    items = _deadline_notifications(projects, _biz_today())
    for e in (state.get("pipeline_events") or []):
        items.append(e)

    # Section order (overdue→today→soon→pipeline→no-deadline), newest-first within.
    items.sort(key=lambda x: x.get("ts") or "", reverse=True)
    items.sort(key=lambda x: x.get("sort", 3))
    unread = sum(1 for x in items if (x.get("ts") or "") > last_seen)
    return {"notifications": items[:_MAX_ITEMS], "unread": unread, "last_seen_at": last_seen}


def mark_seen(actor_email: Optional[str] = None) -> None:
    """Clear the unread badge for everyone (global last-seen = now)."""
    with _LOCK:
        state = _load_state()
        state["last_seen_at"] = _now_iso()
        _save_state(state)
