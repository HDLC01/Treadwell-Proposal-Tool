"""The audit log, which is also the contact timeline's "event" items.

    from bd.events import log_event
    log_event(conn, "confirmed", actor=user, contact_id=8)
    log_event(conn, "owner_changed", actor=user, contact_id=8, detail="Now Greg")
    log_event(conn, "frequency_changed", user, 2, {"from": 4, "to": 6}, detail="4 a year to 6 a year")

`kind` is the timeline's event.action. The contract's words (docs/bd/api-contract.md, labelled by
the page's VERB map): created, confirmed, unconfirmed, duplicate_cleared, owner_changed,
frequency_changed, merged, archived, restored, added_from_quote. Other kinds (settings_changed,
user_added, interaction_deleted, ...) are fine for audit rows without a contact; the timeline shows
only rows with a contact_id.

`actor` is a users row (dict with "id"), a user id, or None (the system). `data` is any
JSON-serialisable dict. Runs inside the caller's transaction: nothing is logged if it rolls back.
Returns the new event id. Ported from BD's events.py (#807) unchanged.
"""
from __future__ import annotations

import json
from typing import Any

TIMELINE_KINDS = ("created", "confirmed", "unconfirmed", "duplicate_cleared", "owner_changed",
                  "frequency_changed", "merged", "archived", "restored", "added_from_quote")


def actor_id(actor: Any) -> Any:
    """The users id of `actor` (a users row, a bare id, or None for the system). interactions_service
    reads an interaction's user_id with it too."""
    if actor is None:
        return None
    if isinstance(actor, dict):
        return actor.get("id")
    return int(actor)


def log_event(conn: Any, kind: str, actor: Any = None, contact_id: int | None = None, data: dict | None = None, *,
              detail: str | None = None, at: Any = None) -> int:
    if not kind or not isinstance(kind, str):
        raise ValueError("an event needs a kind")
    payload = dict(data or {})
    if detail is None and isinstance(payload.get("detail"), str):
        detail = payload["detail"]
    if at is None:
        row = conn.execute(
            "insert into events (kind, actor_id, contact_id, detail, data)"
            " values (%s, %s, %s, %s, %s::jsonb) returning id",
            (kind, actor_id(actor), contact_id, detail, json.dumps(payload, default=str))).fetchone()
    else:
        row = conn.execute(
            "insert into events (kind, actor_id, contact_id, detail, data, at)"
            " values (%s, %s, %s, %s, %s::jsonb, %s) returning id",
            (kind, actor_id(actor), contact_id, detail, json.dumps(payload, default=str), at)).fetchone()
    return row["id"] if isinstance(row, dict) else row[0]
