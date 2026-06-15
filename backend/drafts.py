"""
Project (draft) persistence + activity log — Supabase Postgres.

Two tables (created via the Supabase MCP / SQL editor):

  drafts(id text pk, data jsonb, owner_email text, created_at timestamptz,
         updated_at timestamptz, deleted_at timestamptz)
      One row per project, keyed by the client UUID in the URL (?d=<uuid>).
      `data` is the whole client state blob (we never normalise it).
      deleted_at NULL = active; non-NULL = soft-deleted (in Trash, restorable).

  events(id bigint pk, project_id text, actor_email text, action text,
         detail jsonb, created_at timestamptz)
      Audit trail — who created / generated each proposal. `detail` denormalises
      the project name + total so the History feed needs no join.

The project list is UNIFIED: every signed-in user sees all projects (one
company view), attributed by owner_email.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase_client import get_client


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """No-op: the schema lives in Supabase (provisioned via MCP/SQL editor).
    Kept so the app-startup hook can call it unconditionally."""
    return None


# ── drafts ────────────────────────────────────────────────────────────
def save_draft(draft_id: str, data: Dict[str, Any],
               owner_email: Optional[str] = None) -> Dict[str, str]:
    """Upsert a project. On first save, stamps owner_email + logs a `created`
    event. On update, preserves owner_email/created_at. Returns {id, updated_at}."""
    sb = get_client()
    now = _now_iso()
    existing = sb.table("drafts").select("id").eq("id", draft_id).limit(1).execute()

    if existing.data:
        sb.table("drafts").update({"data": data, "updated_at": now}).eq("id", draft_id).execute()
    else:
        sb.table("drafts").insert({
            "id": draft_id, "data": data, "owner_email": owner_email,
            "created_at": now, "updated_at": now,
        }).execute()
        log_event(draft_id, owner_email, "created", _summary_detail(data))
    return {"id": draft_id, "updated_at": now}


def load_draft(draft_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a project by id. Returns {id, data, created_at, updated_at} or None."""
    sb = get_client()
    res = sb.table("drafts").select("id,data,owner_email,created_at,updated_at") \
        .eq("id", draft_id).limit(1).execute()
    if not res.data:
        return None
    row = res.data[0]
    return {
        "id": row["id"],
        "data": row.get("data") or {},
        "owner_email": row.get("owner_email"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
    }


def delete_draft(draft_id: str) -> bool:
    """Permanently remove a project (hard delete — 'Delete forever' from Trash).
    For normal deletes use trash_draft() so it lands in Trash first. Returns
    True if the project existed."""
    sb = get_client()
    res = sb.table("drafts").delete().eq("id", draft_id).execute()
    return bool(res.data)


def trash_draft(draft_id: str, actor_email: Optional[str] = None) -> bool:
    """Soft-delete: stamp deleted_at so the project moves to Trash — hidden from
    the active list but restorable. Logs a `trashed` event. Returns True if the
    project existed."""
    sb = get_client()
    res = sb.table("drafts").update({"deleted_at": _now_iso()}).eq("id", draft_id).execute()
    rows = res.data or []
    if rows:
        name = (rows[0].get("data") or {}).get("project_name")
        log_event(draft_id, actor_email, "trashed", {"project_name": name, "id": draft_id})
    return bool(rows)


def restore_draft(draft_id: str, actor_email: Optional[str] = None) -> bool:
    """Undo a soft-delete: clear deleted_at so the project returns to the active
    list. Logs a `restored` event. Returns True if the project existed."""
    sb = get_client()
    res = sb.table("drafts").update({"deleted_at": None}).eq("id", draft_id).execute()
    rows = res.data or []
    if rows:
        name = (rows[0].get("data") or {}).get("project_name")
        log_event(draft_id, actor_email, "restored", {"project_name": name, "id": draft_id})
    return bool(rows)


def set_archived(draft_id: str, archived: bool,
                 actor_email: Optional[str] = None) -> bool:
    """Mark a project active/inactive (Kyle's "active/inactive" Projects filter).

    The flag lives INSIDE the `data` blob (`data.archived`) rather than a new
    column — that's backend-agnostic (works the same on cloud Supabase in prod
    and the VPS PostgREST in staging) and needs no schema migration. We
    read-modify-write the blob and deliberately DON'T bump `updated_at`, so
    archiving a finished project doesn't shuffle it to the top of the list.
    Returns True if the project existed."""
    sb = get_client()
    cur = sb.table("drafts").select("data").eq("id", draft_id).limit(1).execute()
    if not cur.data:
        return False
    data = dict(cur.data[0].get("data") or {})
    data["archived"] = bool(archived)
    sb.table("drafts").update({"data": data}).eq("id", draft_id).execute()
    log_event(draft_id, actor_email, "archived" if archived else "unarchived",
              {"project_name": data.get("project_name"), "id": draft_id})
    return True


def list_drafts(limit: int = 300) -> List[Dict[str, Any]]:
    """Unified ACTIVE project list (all owners), newest-updated first."""
    return _list_summaries(trashed=False, limit=limit)


def list_trashed(limit: int = 300) -> List[Dict[str, Any]]:
    """Trashed (soft-deleted) projects, newest-trashed first — powers Trash."""
    return _list_summaries(trashed=True, limit=limit)


def _list_summaries(trashed: bool, limit: int) -> List[Dict[str, Any]]:
    """Shared list builder; `trashed` selects deleted vs active via deleted_at.

    Selects only the card fields (+ the small computed_bid object) via JSON
    extraction instead of the FULL state blob — the blob also holds every edited
    grid cell, so as projects accumulate the old `select=data` ballooned the
    payload. Falls back to the full read on any PostgREST quirk. If the
    deleted_at column doesn't exist yet (pre-migration), the active list degrades
    to unfiltered and the trash list returns []."""
    sb = get_client()
    order_col = "deleted_at" if trashed else "updated_at"

    def _filtered(q):
        # active = deleted_at IS NULL; trash = deleted_at IS NOT NULL
        return q.not_.is_("deleted_at", "null") if trashed else q.is_("deleted_at", "null")

    try:
        cols = ("id,owner_email,created_at,updated_at,deleted_at,"
                "project_name:data->>project_name,"
                "work_type:data->>work_type,"
                "deadline:data->>deadline,"
                "archived:data->>archived,"
                "computed_bid:data->computed_bid")
        try:
            res = _filtered(sb.table("drafts").select(cols)) \
                .order(order_col, desc=True).limit(limit).execute()
        except Exception:  # deleted_at column missing (pre-migration)
            if trashed:
                return []
            res = sb.table("drafts").select(cols).order("updated_at", desc=True).limit(limit).execute()
        return [{
            "id": r["id"],
            "project_name": r.get("project_name") or "(untitled)",
            "total": _bid_total({"computed_bid": r.get("computed_bid")}),
            "work_type": r.get("work_type"),
            "deadline": r.get("deadline"),
            "archived": _truthy(r.get("archived")),
            "owner_email": r.get("owner_email"),
            "created_at": r.get("created_at"),
            "updated_at": r.get("updated_at"),
            "deleted_at": r.get("deleted_at"),
        } for r in (res.data or [])]
    except Exception:  # noqa: BLE001 — fall back to the full-blob read
        try:
            res = _filtered(
                sb.table("drafts").select("id,data,owner_email,created_at,updated_at,deleted_at")
            ).order(order_col, desc=True).limit(limit).execute()
        except Exception:
            if trashed:
                return []
            res = sb.table("drafts").select("id,data,owner_email,created_at,updated_at") \
                .order("updated_at", desc=True).limit(limit).execute()
        return [_summary(row) for row in (res.data or [])]


# ── events (history log) ──────────────────────────────────────────────
def log_event(project_id: Optional[str], actor_email: Optional[str],
              action: str, detail: Optional[Dict[str, Any]] = None) -> None:
    """Append an audit event (best-effort; never breaks the main flow)."""
    try:
        get_client().table("events").insert({
            "project_id": project_id,
            "actor_email": actor_email,
            "action": action,
            "detail": detail or {},
            "created_at": _now_iso(),
        }).execute()
    except Exception:  # noqa: BLE001 — logging must not break save/generate
        pass


def list_events(limit: int = 100) -> List[Dict[str, Any]]:
    """Recent activity, newest first — powers the History view."""
    sb = get_client()
    res = sb.table("events").select("*").order("created_at", desc=True).limit(limit).execute()
    return res.data or []


# ── helpers: pull display fields out of the state blob ────────────────
def _truthy(v: Any) -> bool:
    """Coerce a `data->>archived` value (text "true"/"false"/null, or a real
    bool from the full-blob fallback) to a Python bool."""
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in ("true", "t", "1", "yes")


def _bid_total(data: Dict[str, Any]) -> Optional[float]:
    cb = (data or {}).get("computed_bid") or {}
    fb = cb.get("full_bid") or {}
    if isinstance(fb.get("total_base_bid"), (int, float)):
        return float(fb["total_base_bid"])
    return None


def _summary_detail(data: Dict[str, Any]) -> Dict[str, Any]:
    """Compact project descriptor stored on events so History needs no join."""
    return {
        "project_name": (data or {}).get("project_name"),
        "total": _bid_total(data),
    }


def _summary(row: Dict[str, Any]) -> Dict[str, Any]:
    data = row.get("data") or {}
    return {
        "id": row["id"],
        "project_name": data.get("project_name") or "(untitled)",
        "deadline": data.get("deadline"),
        "city_state": data.get("city_state"),
        "work_type": data.get("work_type"),
        "audience": data.get("audience"),
        "total": _bid_total(data),
        "archived": _truthy(data.get("archived")),
        "lump_sum_display": data.get("lump_sum_display"),
        "owner_email": row.get("owner_email"),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "deleted_at": row.get("deleted_at"),
    }
