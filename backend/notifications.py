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
_LEADS_TTL_S = 55                      # same cadence for the lead-inbox diff
_PORTAL_MSG_TTL_S = 55                 # don't re-poll the portal for messages more often than this
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


# ── lead inbox ─────────────────────────────────────────────────────────
# Same snapshot-diff shape as the pipeline: Basisboard has no webhook we trust
# yet, so "a new lead arrived" is "an id we hadn't seen before". Only non-spam
# bid invites count — addenda, replies and platform noise are a page to browse,
# not something worth a bell.
_LEADS_SNAPSHOT_CAP = 500


def _lead_ids(messages: List[Dict[str, Any]]) -> List[str]:
    return [str(m.get("id")) for m in messages
            if m.get("id") and not m.get("isSpam")
            and str(m.get("communicationType") or "") == "bid_invite"]


def _lead_events(messages: List[Dict[str, Any]], now_iso: str) -> List[Dict[str, Any]]:
    """Bell items for newly arrived leads. `ts` is when we noticed, not the
    email's own timestamp — a message Basisboard backfills a day late still
    deserves to read as unread."""
    out: List[Dict[str, Any]] = []
    for m in messages:
        proj = m.get("project") or {}
        company = ((m.get("company") or {}).get("name") or "").strip()
        out.append({
            "id": f"lead:new:{m.get('id')}", "kind": "lead_new", "icon": "📥",
            "severity": "info", "sort": 3, "ts": now_iso, "link": "/leads.html",
            "title": str(proj.get("name") or m.get("subject") or "New lead"),
            "body": "New lead" + (f" · {company}" if company else ""),
        })
    return out


def _refresh_leads(state: Dict[str, Any]) -> None:
    """Diff the lead inbox against the stored snapshot and record what's new.
    Throttled + best-effort; mutates `state` in place.

    The FIRST run only records the baseline — the inbox holds a couple of weeks
    of invites, and announcing all of them at once is a flood, not news."""
    if not basisboard_client.is_configured():
        return
    synced_at = state.get("leads_synced_at")
    if synced_at:
        try:
            if (_now() - datetime.fromisoformat(synced_at)).total_seconds() < _LEADS_TTL_S:
                return
        except Exception:              # noqa: BLE001 - bad stored value → refresh anyway
            pass
    data = basisboard_client.get_inbox()
    if not data.get("ok"):
        return
    messages = data.get("messages") or []
    ids = _lead_ids(messages)
    now_iso = _now_iso()
    prev = state.get("leads_snapshot")
    # `is not None`, not truthiness: an empty inbox on the first run is still a
    # baseline, and treating it as "no baseline" would flood on the next sweep.
    if prev is not None:
        arrived = set(ids) - set(prev)
        fresh = [m for m in messages if str(m.get("id")) in arrived]
        if fresh:
            events = list(state.get("lead_events") or [])
            events.extend(_lead_events(fresh, now_iso))
            state["lead_events"] = _prune_events(events)
    state["leads_snapshot"] = ids[:_LEADS_SNAPSHOT_CAP]
    state["leads_synced_at"] = now_iso


def add_lead_estimate(draft_id: str, title: str, body: str = "") -> None:
    """Record the autopilot's "I drafted an estimate from a lead" item.

    Pushed rather than diffed: nothing about the Basisboard inbox changes when
    we create a draft, so there's no snapshot that would ever notice. Called
    from the worker thread — best-effort, and never raises into the sweep."""
    did = str(draft_id or "").strip()
    if not did:
        return
    event = {
        "id": f"lead:est:{did}", "kind": "lead_estimate", "icon": "📐",
        "severity": "high", "sort": 3, "ts": _now_iso(),
        "link": f"/?d={did}&edit=1",
        "title": title or "A lead", "body": body or "Estimate drafted from a lead",
    }
    try:
        with _LOCK:
            state = _load_state()
            events = list(state.get("lead_events") or [])
            if any(e.get("id") == event["id"] for e in events):
                return
            events.append(event)
            state["lead_events"] = _prune_events(events)
            _save_state(state)
    except Exception as exc:           # noqa: BLE001 - a bell item is not worth a retry
        log.warning("lead estimate notification failed: %s", exc)


# ── customer portal messages ───────────────────────────────────────────
def _refresh_portal_messages(state: Dict[str, Any]) -> None:
    """Poll the portal's admin API for the newest customer messages (chat +
    inbound-email replies) and cache them in `state`. Throttled + best-effort:
    an unconfigured portal or any HTTP/parse error keeps the previous cache and
    never raises (the bell just shows no new messages). Mutates `state` in place.

    The staff tool never touches the portal_* tables directly — it calls the
    SERVICE_TOKEN-gated admin endpoint, same as main.py's _portal() proxy."""
    base = (os.environ.get("PORTAL_ADMIN_URL") or "").rstrip("/")
    token = (os.environ.get("SERVICE_TOKEN") or "").strip()
    if not base or not token:
        return
    synced_at = state.get("portal_msgs_synced_at")
    if synced_at:
        try:
            if (_now() - datetime.fromisoformat(synced_at)).total_seconds() < _PORTAL_MSG_TTL_S:
                return
        except Exception:              # noqa: BLE001 - bad stored value → refresh anyway
            pass
    import httpx
    try:
        with httpx.Client(timeout=8.0, headers={"X-Service-Token": token}) as c:
            resp = c.get(base + "/api/admin/recent-messages")
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:           # noqa: BLE001 - never let the portal break the bell
        log.warning("portal messages fetch failed: %s", exc)
        return
    if not data.get("ok"):
        return
    state["portal_messages"] = data.get("messages") or []
    state["portal_msgs_synced_at"] = _now_iso()


# The portal feed carries more than chat: submitting a deposit posts its own row.
# Give each type an icon + a body fallback so a payment never reads as "New
# message". `kind` deliberately stays `portal_message` for all of them — the
# toast filter in auth.js keys on it, and a deposit absolutely deserves a toast.
# msg_type -> (icon, empty-body fallback)
_PORTAL_MSG_TYPES = {
    "deposit_submitted": ("💵", "Submitted deposit details"),
}
_PORTAL_MSG_DEFAULT = ("💬", "New message")


def _portal_message_notifications(state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Map the cached portal messages onto bell items. `sort:-1` floats them above
    every other section; the id (`pmsg:<row id>`) lets the frontend dedupe toasts."""
    out: List[Dict[str, Any]] = []
    for r in (state.get("portal_messages") or []):
        rid = r.get("id")
        if rid is None:
            continue
        who = r.get("customer_name") or r.get("author_email") or "A customer"
        proj = r.get("project_name") or "a project"
        pid = r.get("proposal_id")
        icon, empty_body = _PORTAL_MSG_TYPES.get(r.get("msg_type") or "", _PORTAL_MSG_DEFAULT)
        out.append({
            "id": f"pmsg:{rid}", "kind": "portal_message", "icon": icon,
            "severity": "high", "sort": -1, "ts": r.get("created_at") or _EPOCH,
            "title": f"{who} · {proj}",
            "body": r.get("body") or empty_body,
            "link": f"/portal.html?open={pid}" if pid else "/portal.html",
        })
    return out


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


def _dropbox_notifications() -> List[Dict[str, Any]]:
    """Recent 'filed to Dropbox' events (logged by /api/to-dropbox) as bell items,
    newest-first. Clicking one opens the created Dropbox folder."""
    out: List[Dict[str, Any]] = []
    try:
        events = drafts_mod.list_events(limit=100)
    except Exception as exc:               # noqa: BLE001
        log.warning("list_events for dropbox notifications failed: %s", exc)
        return out
    for e in events:
        if e.get("action") != "to_dropbox":
            continue
        d = e.get("detail") or {}
        proj = d.get("project_name") or "A project"
        label = d.get("label")
        out.append({
            "id": f"dbx:{e.get('id')}",
            "kind": "to_dropbox", "icon": "📁", "severity": "info", "sort": 3,
            "ts": e.get("created_at") or _EPOCH,
            "title": proj,
            "body": "Filed to Dropbox" + (f" · {label}" if label else ""),
            "link": d.get("folder_url")
                    or (f"/?d={e.get('project_id')}&edit=1" if e.get("project_id") else "/projects.html"),
        })
        if len(out) >= 25:
            break
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
        try:
            _refresh_leads(state)
        except Exception as exc:       # noqa: BLE001 - never let the lead inbox break the bell
            log.warning("lead refresh failed: %s", exc)
        try:
            _refresh_portal_messages(state)
        except Exception as exc:       # noqa: BLE001 - never let the portal break the bell
            log.warning("portal messages refresh failed: %s", exc)
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
    items.extend(state.get("lead_events") or [])
    items.extend(_dropbox_notifications())
    items.extend(_portal_message_notifications(state))

    # Section order (messages→overdue→today→soon→pipeline→no-deadline), newest-first within.
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
