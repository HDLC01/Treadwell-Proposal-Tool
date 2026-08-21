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

import atomic_json

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
_CRM_TTL_S = 55                        # same cadence for the CRM step diff
_MAX_ITEMS = 60
_TZ_NAME = "America/Chicago"
_EPOCH = "1970-01-01T00:00:00+00:00"


# ── feed tiers: the bell's section order ───────────────────────────────
# ONE RULE — things that HAPPENED outrank things merely DUE.
#
# Hanz, 2026-08-19: "why is this on the bottom, new notifs should be at the top". He was scrolling
# past a wall of 11-hour-old Basisboard rows to find a proposal that had been sent at 13:17 and
# opened at 13:29. The cause was the SECTION order, not the newest-first sort inside a section: the
# deadline buckets came first, and on production they hold 14 overdue + 3 due today + 6 due soon, so
# 23 rows sat above anything that had just happened. Compounding it, a deadline's `ts` is its DUE
# DATE rather than when something occurred, so "newest first" never meant anything recognisable
# within those blocks either.
#
# THE TENSION, stated rather than hidden: an overdue bid deadline is genuinely time-critical, and
# this pushes it BELOW the event feed. It is still the right trade, because a deadline does not
# change — it will read the same tomorrow, and it is also on the board, the bid calendar and the 6am
# digest. A customer opening a proposal is news exactly once, and only the bell says so.
#
# If this bites, the fix is TWO LABELLED GROUPS in the panel ("Recent" / "Deadlines") so neither
# hides the other — NOT restoring an order that buries today's events behind last week's dates. The
# rejected alternative was leaving the tiers alone and sorting the whole feed by `ts`: that reads
# worse, because a deadline's `ts` is a due date and would interleave future dates with past events.
_TIER_MESSAGE = 0        # a customer said something — outranks us moving a card
_TIER_CRM_STEP = 1       # our OWN pipeline: sent / viewed / approved / deposit / closed lost
_TIER_ACTIVITY = 2       # third-party + filing: Basisboard pipeline, lead inbox, Dropbox
_TIER_OVERDUE = 3
_TIER_DUE_TODAY = 4
_TIER_DUE_SOON = 5
_TIER_NO_DEADLINE = 6
_TIER_UNKNOWN = 9        # an item that forgot its tier is a bug; a bug does not get the top slot
# Named instead of repeated as bare literals because every category emits its tier from SEVERAL
# places (three for the Basisboard diff, three for crm_step), and one missed literal splits a
# category across two sections — which is exactly what made the old order impossible to read.


# ── how the 60 slots are divided ──────────────────────────────────────
# The retiering above fixed the ORDER and broke the CONTENTS. `items[:_MAX_ITEMS]` cut the feed
# AFTER the sort, so with events now on top, events took all 60 slots: production returned ZERO
# rows whose kind starts with `deadline_` while it held 14 overdue + 3 due today + 6 due soon bids.
# Hanz asked for new things at the top; he did not ask for overdue bids to vanish, and an overdue
# bid is money.
#
# So the cap is applied PER GROUP before the global trim. This is the slot half of the "two labelled
# groups" idea in the tier block — the panel is still one list, but the two halves no longer compete
# for the same 60 rows.
#
# THE NUMBERS, and why these: 24 deadline slots covers the whole URGENT deadline load measured on
# production on 2026-08-19 (14 overdue + 3 due today + 6 due soon = 23) with one row of headroom, so
# the loudest possible event day still cannot push a dated bid nobody has answered off the panel.
# Events keep the remaining 36 and lead it regardless of how many they are. The rejected split was
# 40/20: rounder, but 20 is under the 23 rows prod already carries, so it would drop due-soon bids on
# exactly the busy days when nobody has time to go read the board instead.
#
# Either side's unclaimed slots spill to the other (see _cap_by_group), so a quiet morning fills the
# panel with whatever there IS rather than leaving the other group's reserve as empty space.
_GROUP_EVENTS = "events"          # something HAPPENED: message / crm step / activity
_GROUP_DEADLINES = "deadlines"    # merely DUE: overdue / today / soon / no deadline
_GROUP_UNTIERED = "untiered"      # a source that shipped without a `sort` — reserves nothing

_DEADLINE_SLOTS = 24
_EVENT_SLOTS = _MAX_ITEMS - _DEADLINE_SLOTS
# Derived from _MAX_ITEMS rather than written as two literals so the reserves can never sum to more
# than the panel renders — a split that oversubscribes the total would put the bound back at the
# mercy of a defensive slice.
_GROUP_RESERVE = {_GROUP_EVENTS: _EVENT_SLOTS, _GROUP_DEADLINES: _DEADLINE_SLOTS}

_TIER_GROUP = {
    _TIER_MESSAGE: _GROUP_EVENTS,
    _TIER_CRM_STEP: _GROUP_EVENTS,
    _TIER_ACTIVITY: _GROUP_EVENTS,
    _TIER_OVERDUE: _GROUP_DEADLINES,
    _TIER_DUE_TODAY: _GROUP_DEADLINES,
    _TIER_DUE_SOON: _GROUP_DEADLINES,
    _TIER_NO_DEADLINE: _GROUP_DEADLINES,
}


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
            atomic_json.write_json(_STATE_FILE, state, make_parent=False)   # atomic, retried
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
                "severity": "info", "sort": _TIER_ACTIVITY, "ts": now_iso, "link": "/crm.html",
                "title": name,
                "body": f"New bid in the pipeline · {p.get('stage_name') or 'Unstaged'}",
            })
            continue
        if bool(p.get("awarded")) and not old.get("awarded"):
            changes.append({
                "id": f"pl:award:{pid}:{now_iso}", "kind": "pipeline_awarded", "icon": "🏆",
                "severity": "high", "sort": _TIER_ACTIVITY, "ts": now_iso, "link": "/crm.html",
                "title": name, "body": "Bid awarded 🎉",
            })
        elif p.get("stage_id") != old.get("stage_id"):
            frm = old.get("stage_name")
            changes.append({
                "id": f"pl:stage:{pid}:{now_iso}", "kind": "pipeline_stage", "icon": "➡️",
                "severity": "info", "sort": _TIER_ACTIVITY, "ts": now_iso, "link": "/crm.html",
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
            "severity": "info", "sort": _TIER_ACTIVITY, "ts": now_iso, "link": "/leads.html",
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
        # ACTIVITY, not CRM_STEP: this is the lead inbox's own follow-through, and it rides in
        # `lead_events` with the rest of the inbox. A crm_step is something a CUSTOMER did to a
        # proposal that exists; drafting an estimate is us reacting to a Basisboard invite.
        "id": f"lead:est:{did}", "kind": "lead_estimate", "icon": "📐",
        "severity": "high", "sort": _TIER_ACTIVITY, "ts": _now_iso(),
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
    """Map the cached portal messages onto bell items. `_TIER_MESSAGE` floats them above every
    other section; the id (`pmsg:<row id>`) lets the frontend dedupe toasts."""
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
            "severity": "high", "sort": _TIER_MESSAGE, "ts": r.get("created_at") or _EPOCH,
            "title": f"{who} · {proj}",
            "body": r.get("body") or empty_body,
            "link": f"/portal.html?open={pid}" if pid else "/portal.html",
        })
    return out


# ── the CRM's own steps ────────────────────────────────────────────────
# Hanz, 2026-08-19: "why are the notif bell not working?" → "Every step of the CRM, message, chat
# notif".
#
# It WAS working, and that was the confusing part. The bell already carried customer messages,
# deposit submissions, bid deadlines, the Basisboard pipeline and the lead inbox — so it looked
# alive while saying nothing about our OWN pipeline. Nothing told you a proposal had been viewed,
# approved, closed lost, or that a deposit had landed. Those are the steps the board is made of.
#
# Same snapshot-diff shape as _refresh_pipeline, and for the same reason: the portal has no webhook
# pointed at us, so "this changed" is "this differs from what we saw last time". The three status
# fields ARE the steps, so they are diffed directly rather than run through a re-implementation of
# crm-core's stage() — a second copy of that ordering is exactly the drift this codebase keeps
# warning about, and it would put a wrong word in a notification nobody can correct.
_CRM_SNAPSHOT_CAP = 800

# field -> {new value: (icon, sentence, severity)}. A value absent from a field's map is a state
# change nobody needs a bell for.
_CRM_STEPS = {
    "proposal_status": {
        "viewed":      ("👀", "Opened the proposal", "info"),
        "approved":    ("✅", "Approved the proposal", "high"),
        "closed_lost": ("⛔", "Closed lost", "info"),
    },
    "deposit_status": {
        # NOT "submitted". The customer submitting a deposit already posts a portal message row,
        # which reaches the bell as a 💵 item AND a toast (see _PORTAL_MSG_TYPES). Emitting a step
        # for it too would show the same event twice, which is how a bell stops being read.
        "requested":   ("🧾", "Deposit invoice issued", "info"),
        "received":    ("💰", "Deposit received", "high"),
    },
    "contacts_status": {
        "received":    ("📇", "Sent their project contacts", "info"),
    },
}


def _crm_snapshot(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        pid = r.get("proposal_id")
        if not pid:
            continue
        out[str(pid)] = {
            "proposal_status": r.get("proposal_status") or "",
            "deposit_status": r.get("deposit_status") or "",
            "contacts_status": r.get("contacts_status") or "",
            "name": r.get("project_name") or "",
        }
        if len(out) >= _CRM_SNAPSHOT_CAP:
            break
    return out


def _diff_crm(prev: Dict[str, Any], rows: List[Dict[str, Any]],
              now_iso: str) -> List[Dict[str, Any]]:
    """One item per interesting status change since the last look.

    A proposal_id we have never seen is a FIRST SEND — the row does not exist in the portal until
    somebody publishes — so it gets one "Proposal sent" item and none of the per-field ones. Without
    that special case a first send would fire two or three notifications at once for what a person
    experienced as pressing one button."""
    out: List[Dict[str, Any]] = []
    for r in rows:
        pid = str(r.get("proposal_id") or "")
        if not pid:
            continue
        name = r.get("project_name") or "A project"
        link = f"/portal.html?open={pid}"
        old = prev.get(pid)
        if old is None:
            out.append({
                "id": f"crm:sent:{pid}:{now_iso}", "kind": "crm_step", "icon": "📤",
                "severity": "info", "sort": _TIER_CRM_STEP, "ts": now_iso, "link": link,
                "title": name, "body": "Proposal sent to the customer",
            })
            continue
        for field, steps in _CRM_STEPS.items():
            now_val = r.get(field) or ""
            if now_val == (old.get(field) or ""):
                continue
            step = steps.get(now_val)
            if not step:
                continue
            icon, sentence, severity = step
            out.append({
                # The VALUE is in the id, not just the field: a deposit that goes requested →
                # received inside one poll window would otherwise collide on `crm:deposit_status:…`
                # and the second item would be deduped away by the frontend.
                "id": f"crm:{field}:{now_val}:{pid}:{now_iso}", "kind": "crm_step", "icon": icon,
                "severity": severity, "sort": _TIER_CRM_STEP, "ts": now_iso, "link": link,
                "title": name, "body": sentence,
            })
    return out


def _refresh_crm(state: Dict[str, Any]) -> None:
    """Poll the portal's pipeline, diff the statuses, append the changes. Best-effort and throttled,
    exactly like the other three refreshers: an unconfigured portal or any error keeps the previous
    snapshot and never raises.

    FIRST RUN RECORDS A BASELINE AND EMITS NOTHING. Otherwise every proposal in the database would
    arrive as a fresh 'Proposal sent' the moment this deploys — sixty notifications about things
    that happened weeks ago, which is worse than the silence it replaces."""
    base = (os.environ.get("PORTAL_ADMIN_URL") or "").rstrip("/")
    token = (os.environ.get("SERVICE_TOKEN") or "").strip()
    if not base or not token:
        return
    synced_at = state.get("crm_synced_at")
    if synced_at:
        try:
            if (_now() - datetime.fromisoformat(synced_at)).total_seconds() < _CRM_TTL_S:
                return
        except Exception:              # noqa: BLE001 - bad stored value → refresh anyway
            pass
    import httpx
    try:
        with httpx.Client(timeout=8.0, headers={"X-Service-Token": token}) as c:
            resp = c.get(base + "/api/admin/pipeline")
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:           # noqa: BLE001 - never let the portal break the bell
        log.warning("crm pipeline fetch failed: %s", exc)
        return
    rows = data.get("proposals") or []
    if not rows:
        # An empty list is far more likely to be a portal that answered oddly than every proposal
        # having been deleted. Replacing the snapshot with {} would make the NEXT poll announce the
        # whole database as newly sent.
        return
    now_iso = _now_iso()
    prev = state.get("crm_snapshot")
    if prev:
        changes = _diff_crm(prev, rows, now_iso)
        if changes:
            events = list(state.get("crm_events") or [])
            events.extend(changes)
            state["crm_events"] = _prune_events(events)
    state["crm_snapshot"] = _crm_snapshot(rows)
    state["crm_synced_at"] = now_iso


def _draft_event_notifications() -> List[Dict[str, Any]]:
    """Steps that happen to a project the PORTAL has never heard of.

    A bid closed lost before it was ever sent (2026-08-19) has no portal row, so _diff_crm cannot
    see it — it is recorded on the draft and logged to our own events table. Same for reactivating
    one. Read from the log rather than diffed, because unlike a status field these events already
    carry their own timestamp and actor."""
    steps = {
        "closed_lost": ("⛔", "Closed lost before it was sent"),
        "reactivated": ("↩️", "Reopened — back in Created but not sent"),
    }
    out: List[Dict[str, Any]] = []
    try:
        events = drafts_mod.list_events(limit=100)
    except Exception as exc:               # noqa: BLE001
        log.warning("list_events for CRM notifications failed: %s", exc)
        return out
    for e in events:
        step = steps.get(e.get("action") or "")
        if not step:
            continue
        icon, sentence = step
        d = e.get("detail") or {}
        reason = d.get("reason")
        out.append({
            "id": f"dev:{e.get('id')}", "kind": "crm_step", "icon": icon,
            "severity": "info", "sort": _TIER_CRM_STEP, "ts": e.get("created_at") or _EPOCH,
            "title": d.get("project_name") or "A project",
            "body": sentence + (f" · {reason.replace('_', ' ')}" if reason else ""),
            "link": "/portal.html",
        })
        if len(out) >= 25:
            break
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
                "severity": "low", "sort": _TIER_NO_DEADLINE,
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
                "severity": "high", "sort": _TIER_OVERDUE, "ts": _date_iso(dl), "title": name,
                "body": f"Overdue by {n} day{'s' if n != 1 else ''} ({dl_str})", "link": link,
            })
        elif days == 0:
            out.append({
                "id": f"dl:today:{pid}", "kind": "deadline_today", "icon": "🟠",
                "severity": "high", "sort": _TIER_DUE_TODAY, "ts": _date_iso(dl), "title": name,
                "body": f"Due today ({dl_str})", "link": link,
            })
        elif days <= 7:
            out.append({
                "id": f"dl:soon:{pid}", "kind": "deadline_soon", "icon": "🟡",
                "severity": "medium", "sort": _TIER_DUE_SOON, "ts": _date_iso(dl - timedelta(days=7)),
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
            "kind": "to_dropbox", "icon": "📁", "severity": "info", "sort": _TIER_ACTIVITY,
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
def _retier(stored: Optional[List[Dict[str, Any]]], tier: int) -> List[Dict[str, Any]]:
    """Re-stamp the section tier on events read back OUT of the state file.

    The state file is a 30-day archive written by whatever code was deployed when each event
    happened, so its items carry whatever `sort` was current then. Without this, the 2026-08-19
    retiering would leave up to a month of stored Basisboard/lead/CRM events sitting at the old
    activity number — which is now the OVERDUE DEADLINE tier — so the very rows this change moves off
    the bottom would come back in the middle of the deadline block for a month.

    The rejected alternative was bumping a version key and discarding the stored events on first
    read: that throws away real bell history to correct a number we can simply recompute. Returns
    copies, so the recomputed tier is never written back into the file."""
    return [{**e, "sort": tier} for e in (stored or [])]


def _group_of(item: Dict[str, Any]) -> str:
    """Which pool of slots an item draws from. Reads the tier through the SAME missing-key default
    as the feed sort, so an item that shipped without a `sort` is treated consistently by both."""
    return _TIER_GROUP.get(item.get("sort", _TIER_UNKNOWN), _GROUP_UNTIERED)


def _cap_by_group(items: List[Dict[str, Any]], total: int = _MAX_ITEMS) -> List[Dict[str, Any]]:
    """Trim an already-ordered feed to `total` rows so neither group can starve the other.

    `items` must arrive in final display order (tier, then newest-first). This picks WHICH rows
    survive and re-emits them in that same order, so it can never reorder the feed. The rejected
    alternative was bucketing and concatenating the kept buckets: it gives the identical answer today
    only because the tier groups happen to be contiguous, and would start quietly reordering the
    panel the day a group spans a gap or a tier moves between groups.

    Two passes:
      1. Nobody exceeds its reserve, which is what guarantees each group a floor no matter how loud
         the other one is. Untiered items reserve nothing — a source that forgot its tier is a bug,
         and a bug must not evict a bid deadline to make room for itself.
      2. Slots a quiet group didn't claim go to the groups that still have rows waiting, so 2
         deadlines and 100 events fills the panel with 58 events rather than showing 38 rows.
    """
    buckets: Dict[str, List[int]] = {}
    for i, item in enumerate(items):
        buckets.setdefault(_group_of(item), []).append(i)
    keep = {g: min(len(idx), _GROUP_RESERVE.get(g, 0)) for g, idx in buckets.items()}
    spare = total - sum(keep.values())
    # Insertion order is the order the groups first appear in the sorted feed, i.e. their own tier
    # order — so when both sides want the spare slots the higher-ranked group gets first call.
    for group, idx in buckets.items():
        if spare <= 0:
            break
        take = min(len(idx) - keep[group], spare)
        keep[group] += take
        spare -= take
    chosen = sorted(i for group, idx in buckets.items() for i in idx[:keep[group]])
    return [items[i] for i in chosen]


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
        try:
            _refresh_crm(state)
        except Exception as exc:       # noqa: BLE001 - never let the CRM diff break the bell
            log.warning("crm refresh failed: %s", exc)
        _save_state(state)
        last_seen = state.get("last_seen_at") or _EPOCH

    try:
        projects = drafts_mod.list_drafts()
    except Exception as exc:           # noqa: BLE001
        log.warning("list_drafts for notifications failed: %s", exc)
        projects = []

    items = _deadline_notifications(projects, _biz_today())
    items.extend(_retier(state.get("pipeline_events"), _TIER_ACTIVITY))
    items.extend(_retier(state.get("lead_events"), _TIER_ACTIVITY))
    items.extend(_dropbox_notifications())
    items.extend(_portal_message_notifications(state))
    # Our own pipeline's steps, from both sides: a proposal the customer has (diffed off the portal)
    # and a bid closed before it was ever sent (our events log).
    #
    # `_TIER_CRM_STEP` — its OWN tier, above the Basisboard pipeline and the lead inbox rather than
    # sharing the activity block with them (2026-08-19). Our pipeline moving matters more than a
    # third party's, and Basisboard alone can produce dozens of rows in a sweep, which is what buried
    # an approval last time. Within a tier the order is newest-first.
    items.extend(_retier(state.get("crm_events"), _TIER_CRM_STEP))
    items.extend(_draft_event_notifications())

    # ORDER: everything that HAPPENED, newest first, then the deadlines by urgency.
    #
    # Hanz, 2026-08-21, looking at a panel whose top row was eight days old: "notification is still
    # showing the older ones and not in chronological order". He was right, and it was this sort.
    # It used to order events by TIER first (messages, then CRM steps, then activity) and only then
    # by time, with a stable sort — so tier won outright and a nine-day-old customer message sat
    # above everything that happened today, permanently. Worse, the event slots filled up with old
    # messages and pushed genuinely new rows off the end, which is the other half of what he saw.
    #
    # The tier split was right about ONE thing and wrong about the other. Right: an event outranks a
    # deadline, because a deadline reads the same tomorrow and an event is news exactly once. Wrong:
    # ranking KINDS of event against each other, which quietly ranked them against time as well. A
    # customer message does matter more than us moving a card — but not a week later. So the three
    # event tiers now share one bucket ordered by time alone, and the deadlines keep their urgency
    # order underneath, where nothing about them is time-sensitive in the same way.
    #
    # An item that shipped without a `sort` still lands LAST, not first: a source that forgot its
    # tier is a bug, and a bug does not get the top slot of the feed the whole team reads first.
    _EVENTS_RANK, _DEADLINES_RANK, _UNTIERED_RANK = 0, 1, 2

    def _rank(item: Dict[str, Any]) -> tuple:
        tier = item.get("sort", _TIER_UNKNOWN)
        group = _TIER_GROUP.get(tier)
        if group == _GROUP_EVENTS:
            return (_EVENTS_RANK, 0)            # time alone orders these
        if group == _GROUP_DEADLINES:
            return (_DEADLINES_RANK, tier)      # overdue before today before soon
        return (_UNTIERED_RANK, tier)

    items.sort(key=lambda x: x.get("ts") or "", reverse=True)
    items.sort(key=_rank)
    # Per-group BEFORE the total, or the winning group takes all 60 — see the _GROUP_* block.
    items = _cap_by_group(items, _MAX_ITEMS)
    # `unread` is counted AFTER the trim, deliberately, and that is the correct side: the badge is a
    # promise about what you will find when you open the panel, and the panel has no pager — it
    # renders exactly these rows and nothing else. Counting the whole pre-trim feed sent people
    # hunting for a "17" they could only ever find 9 of, and `mark_seen` clears the badge globally,
    # so an item counted but never shown is cleared without anyone having read it. The reverse error
    # is just as real (a badge that undercounts hides news), which is what the per-group cap above
    # is for: no whole CATEGORY can now be trimmed away, so what the badge omits is only the tail of
    # a group whose head is on screen.
    unread = sum(1 for x in items if (x.get("ts") or "") > last_seen)
    return {"notifications": items, "unread": unread, "last_seen_at": last_seen}


def mark_seen(actor_email: Optional[str] = None) -> None:
    """Clear the unread badge for everyone (global last-seen = now)."""
    with _LOCK:
        state = _load_state()
        state["last_seen_at"] = _now_iso()
        _save_state(state)
