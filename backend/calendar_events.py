"""Treadwell's own calendar entries — the writable half of the Bid Calendar.

WHY THIS TABLE EXISTS. The Bid Calendar started as a read-only view over Basisboard's
bids, because our Basisboard integration never writes: their API is a source we read, and
pushing changes back is not something we do. But the calendar is meant to become the one
Treadwell staff actually use as they move off Basisboard — so it has to accept work that
never came from Basisboard at all.

Hence two sources on one grid:

  * Basisboard bids — mirrored, read-only, marked as such. Editing one is refused with an
    explanation rather than accepted-then-reverted. A staff member who edits a bid, sees it
    change, and finds it back to the old value after the next 5-minute sync would rightly
    conclude the tool loses data. Refusing is the honest answer while Basisboard remains
    the system of record for those.
  * These rows — created, edited and deleted in the tool, owned by us entirely.

Once Basisboard is gone, only these remain and nothing about them has to change.

  calendar_events(id text pk, title text, deadline_at timestamptz, kind text,
                  customer text, location text, value numeric, estimator_email text,
                  stage text, notes text, project_id text, owner_email text,
                  created_at timestamptz, updated_at timestamptz, deleted_at timestamptz)

Provisioned in Supabase via MCP/SQL editor like `drafts` — the app role cannot ALTER.

DELETES ARE SOFT. `deleted_at` non-NULL hides a row. A calendar is a work queue; an
accidental delete that actually destroyed a bid deadline would cost a job, and every other
destructive action in this app is already recoverable (see Trash).

DATES. `deadline_at` is stored as a full UTC timestamptz and rendered in Central by the
frontend, the same contract the Basisboard rows use. Storing a bare date would throw away
the cut-off time, which is most of what a bid deadline IS.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase_client import get_client

log = logging.getLogger(__name__)

TABLE = "calendar_events"

# What a caller is allowed to set. Anything else in the payload is ignored rather than
# stored: an unknown key is a client bug, and silently persisting it makes the row shape
# unpredictable for every later reader.
WRITABLE = ("title", "deadline_at", "kind", "customer", "location", "value",
            "estimator_email", "stage", "notes", "project_id")

KINDS = ("bid", "site_visit", "submission", "reminder", "other")
DEFAULT_KIND = "bid"

_MAX_TEXT = 500
_MAX_NOTES = 4000


class ValidationError(ValueError):
    """A caller-fixable problem. The message is shown to the user, so it says what to do."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, limit: int = _MAX_TEXT) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def parse_deadline(value: Any) -> Optional[str]:
    """Normalise an incoming deadline to a UTC ISO string, or None.

    Accepts what a browser sends: a full ISO timestamp, or the `datetime-local` form with
    no zone. A NAIVE value is treated as UTC because that is what the frontend sends after
    converting from the picker — guessing the server's local zone here is how a 2pm Central
    deadline becomes 2pm UTC and lands on the calendar at 9am."""
    if value in (None, ""):
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValidationError("That deadline isn't a date we can read.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _clean_value(raw: Any) -> Optional[float]:
    """Dollars. Tolerates "$1,200" because people paste from a spreadsheet."""
    if raw in (None, ""):
        return None
    if isinstance(raw, (int, float)):
        num = float(raw)
    else:
        stripped = re.sub(r"[$,\s]", "", str(raw))
        try:
            num = float(stripped)
        except ValueError:
            raise ValidationError("That value isn't a number.")
    if num < 0:
        raise ValidationError("A bid value can't be negative.")
    if num > 1e11:
        raise ValidationError("That value is implausibly large — check the figure.")
    return num


def validate(payload: Dict[str, Any], *, partial: bool = False) -> Dict[str, Any]:
    """Shape and check a create/update payload. Raises ValidationError for anything a
    person can fix; returns only the columns we intend to write."""
    if not isinstance(payload, dict):
        raise ValidationError("Nothing to save.")

    out: Dict[str, Any] = {}

    if "title" in payload or not partial:
        title = _clean_text(payload.get("title"))
        if not title:
            raise ValidationError("Give it a name so it can be found later.")
        out["title"] = title

    if "deadline_at" in payload or not partial:
        out["deadline_at"] = parse_deadline(payload.get("deadline_at"))

    if "kind" in payload or not partial:
        kind = _clean_text(payload.get("kind"), 40).lower() or DEFAULT_KIND
        if kind not in KINDS:
            raise ValidationError("That isn't a kind of calendar entry we know about.")
        out["kind"] = kind

    if "value" in payload or not partial:
        out["value"] = _clean_value(payload.get("value"))

    for col, limit in (("customer", _MAX_TEXT), ("location", _MAX_TEXT),
                       ("stage", 80), ("project_id", 80), ("notes", _MAX_NOTES)):
        if col in payload or not partial:
            out[col] = _clean_text(payload.get(col), limit) or None

    if "estimator_email" in payload or not partial:
        email = _clean_text(payload.get("estimator_email"), 200).lower() or None
        # Deliberately loose: the roster is the authority on who exists, and rejecting an
        # address that merely looks odd would block a legitimate one. Only obvious
        # nonsense is refused.
        if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
            raise ValidationError("That estimator address doesn't look like an email.")
        out["estimator_email"] = email

    return out


def _shape(row: Dict[str, Any]) -> Dict[str, Any]:
    """One row, in the same vocabulary the calendar's Basisboard rows use — so the page can
    render both from one code path instead of branching per source.

    `source` and `editable` are what the UI needs to know it may offer an edit button; they
    are computed here rather than assumed there, so the answer can only be given in one
    place."""
    return {
        "id": row.get("id"),
        "name": row.get("title") or "Untitled",
        "bid_deadline_at": row.get("deadline_at"),
        "kind": row.get("kind") or DEFAULT_KIND,
        "customer": row.get("customer") or "",
        "location": row.get("location") or "",
        "quote": row.get("value"),
        "estimator_email": row.get("estimator_email") or "",
        "estimator_ids": [row["estimator_email"]] if row.get("estimator_email") else [],
        "stage_id": row.get("stage") or "",
        "notes": row.get("notes") or "",
        "project_id": row.get("project_id") or "",
        "owner_email": row.get("owner_email") or "",
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "archived": False,
        "source": "treadwell",
        "editable": True,
    }


_COLS = ("id,title,deadline_at,kind,customer,location,value,estimator_email,stage,notes,"
         "project_id,owner_email,created_at,updated_at")


def list_events() -> List[Dict[str, Any]]:
    """Every live entry. Never raises: the calendar's Basisboard half must still render if
    this table is missing or unreachable, because a broken read here would otherwise take
    down a page that mostly shows something else."""
    try:
        sb = get_client()
        res = (sb.table(TABLE).select(_COLS)
               .is_("deleted_at", "null")
               .order("deadline_at", desc=False)
               .limit(5000).execute())
        return [_shape(r) for r in (res.data or [])]
    except Exception as exc:  # noqa: BLE001
        log.warning("calendar_events list failed: %s", exc)
        return []


def get_event(event_id: str) -> Optional[Dict[str, Any]]:
    sb = get_client()
    res = (sb.table(TABLE).select(_COLS)
           .eq("id", event_id).is_("deleted_at", "null").limit(1).execute())
    return _shape(res.data[0]) if res.data else None


def create_event(payload: Dict[str, Any], owner_email: Optional[str]) -> Dict[str, Any]:
    fields = validate(payload, partial=False)
    now = _now_iso()
    row = dict(fields, id=str(uuid.uuid4()), owner_email=owner_email,
               created_at=now, updated_at=now)
    sb = get_client()
    sb.table(TABLE).insert(row).execute()
    return _shape(row)


def update_event(event_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Patch an entry. Returns None if it doesn't exist (or is already deleted), so the
    caller can 404 rather than reporting a successful write to nothing."""
    fields = validate(payload, partial=True)
    if not fields:
        raise ValidationError("Nothing to change.")
    sb = get_client()
    existing = (sb.table(TABLE).select("id").eq("id", event_id)
                .is_("deleted_at", "null").limit(1).execute())
    if not existing.data:
        return None
    fields["updated_at"] = _now_iso()
    sb.table(TABLE).update(fields).eq("id", event_id).execute()
    return get_event(event_id)


def delete_event(event_id: str) -> bool:
    """Soft delete. False if there was nothing live to delete."""
    sb = get_client()
    existing = (sb.table(TABLE).select("id").eq("id", event_id)
                .is_("deleted_at", "null").limit(1).execute())
    if not existing.data:
        return False
    sb.table(TABLE).update({"deleted_at": _now_iso()}).eq("id", event_id).execute()
    return True
