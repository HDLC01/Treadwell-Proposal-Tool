"""The app's Settings object (api-contract.md "Settings"): defaults here, admin changes in the
`settings` table (one row per top-level key, value jsonb), merged on read.

    appsettings.load(conn) -> dict           the full Settings object, as GET /api/settings sends it
    appsettings.store(conn, changes, actor_id=None)   upsert top-level keys (no validation here:
                                             PUT /api/admin/settings validates the merged result
                                             first, then stores it)
    appsettings.defaults() -> dict           a fresh copy of the defaults, the environment applied
    appsettings.READ_ONLY_KEYS, PICK_LISTS

Read-only keys (READ_ONLY_KEYS) always come from defaults(), whatever a row says: they are the
counting rule and the clock, not preferences. `weekly` and `default_frequency` rows are merged
over their defaults key by key, so a row holding only {"new_count": 6, "followup_count": 4} keeps
the default run day and hour; a stored sub-key the defaults do not have (the retired
`default_frequency.bd`) is dropped.

`bd_cadence` ('weekly' | 'monthly' | 'quarterly', default 'quarterly') is the one BD cadence;
CADENCE_FREQ turns it into live touches a year (52 / 12 / 4).

Two defaults follow the environment: `weekly.enabled` / `weekly.run_hour` (BD_WEEKLY_ENABLED /
BD_WEEKLY_HOUR). A stored row wins over them. `ai_enabled` is false: BD's AI setting was not carried
into the proposal tool (#802), and nothing in BD calls out today.
"""
from __future__ import annotations

import copy
import json
from typing import Any

from . import config

_BASE: dict[str, Any] = {
    "bd_cadence": "quarterly",
    "default_frequency": {"maintenance": 3},
    "maintenance_touch_days": 120,
    "weekly": {"new_count": 5, "followup_count": 5, "run_day": "friday", "run_hour": 16, "enabled": True},
    "weekly_meeting_goal": 5,
    "non_dsbc_website_min": 1,
    "lead_sources": ["Current Account", "DSBC Sales", "Website Lead", "Other/Misc"],
    "system_lead_sources": ["DSBC Sales", "Website Lead"],
    "industries": ["Manufacturing", "Other", "Food Processing", "GC", "Life Science", "Restaurant",
                   "Education", "Warehouse", "Retail", "Healthcare"],
    "stages": ["Meeting Set", "Met", "Proposal", "Won"],
    "account_types": ["Utility", "Manufacturing", "Pharma", "GC"],
    "interaction_kinds": ["call", "voicemail", "meeting", "email", "sms", "note", "hosted"],
    "touch_kinds": ["call (answered or meeting set)", "meeting", "hosted"],
    "call_outcomes": ["answered", "voicemail", "no_answer", "meeting_set"],
    "ai_enabled": False,
    "timezone": "America/Chicago",
}

READ_ONLY_KEYS = ("system_lead_sources", "interaction_kinds", "touch_kinds", "call_outcomes",
                  "timezone", "maintenance_touch_days")
PICK_LISTS = ("lead_sources", "industries", "stages", "account_types")
MERGED_KEYS = ("weekly", "default_frequency")
BD_CADENCES = ("weekly", "monthly", "quarterly")
# Live touches a year for each BD cadence word (bd-core.js CADENCE_FREQ, SQL bd_cadence_frequency).
CADENCE_FREQ = {"weekly": 52, "monthly": 12, "quarterly": 4}


def defaults() -> dict:
    """A fresh copy of the defaults, with the environment-driven ones applied."""
    d = copy.deepcopy(_BASE)
    d["weekly"]["enabled"] = bool(config.BD_WEEKLY_ENABLED)
    d["weekly"]["run_hour"] = int(config.BD_WEEKLY_HOUR)
    return d


def merge(base: dict, rows: dict) -> dict:
    """`rows` ({key: value}) laid over `base` with the read-only and merge rules."""
    out = copy.deepcopy(base)
    for key, value in rows.items():
        if key in READ_ONLY_KEYS or key not in out:
            continue
        if key in MERGED_KEYS and isinstance(value, dict) and isinstance(out.get(key), dict):
            # Stored sub-keys the app no longer has (default_frequency.bd) are dropped, not served.
            out[key].update({k: copy.deepcopy(v) for k, v in value.items() if k in out[key]})
        else:
            out[key] = copy.deepcopy(value)
    return out


def load(conn: Any) -> dict:
    rows = {r["key"]: r["value"] for r in conn.execute("select key, value from settings").fetchall()}
    return merge(defaults(), rows)


def store(conn: Any, changes: dict, actor_id: int | None = None) -> None:
    """Upsert each top-level key of `changes` (read-only keys are skipped). The caller has
    validated the merged result."""
    for key, value in changes.items():
        if key in READ_ONLY_KEYS:
            continue
        conn.execute(
            "insert into settings (key, value, updated_at, updated_by) values (%s, %s::jsonb, bd_now(), %s)"
            " on conflict (key) do update set value = excluded.value, updated_at = excluded.updated_at,"
            " updated_by = excluded.updated_by",
            (key, json.dumps(value), actor_id))
