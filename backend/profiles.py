"""User profiles + admin operations (Supabase).

Roles: user < admin < super_admin. The `profiles` table is the source of truth
(created on signup by the DB trigger in supabase_schema.sql, which also bootstraps
hanz@wetreadwell.com as super_admin). Google SSO has no passwords, so there is no
password-reset action — actions are: set role · pause · ban/unban · delete.

Guardrails (mirrors ARIA):
  - the super_admin row is immutable via the panel (anti-lockout)
  - nobody can act on themselves
  - only a super_admin may manage an admin or grant the admin role
  - admins manage regular users only
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from supabase_client import get_client

_PROFILE_COLS = "id,email,full_name,role,status,banned_at,banned_until,ban_reason,created_at,updated_at"
_BAN_FOREVER = "876000h"  # ~100 years ≈ permanent (Supabase Admin API ban_duration)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── reads ─────────────────────────────────────────────────────────────
def get_by_email(email: str) -> Optional[Dict[str, Any]]:
    if not email:
        return None
    res = get_client().table("profiles").select(_PROFILE_COLS) \
        .eq("email", email.lower()).limit(1).execute()
    return res.data[0] if res.data else None


def get_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    res = get_client().table("profiles").select(_PROFILE_COLS) \
        .eq("id", user_id).limit(1).execute()
    return res.data[0] if res.data else None


def list_users(search: str = "", role: str = "") -> List[Dict[str, Any]]:
    q = get_client().table("profiles").select(_PROFILE_COLS).order("created_at", desc=True).limit(500)
    if role in ("user", "admin", "super_admin"):
        q = q.eq("role", role)
    if search:
        # ILIKE on email OR full_name
        q = q.or_(f"email.ilike.%{search}%,full_name.ilike.%{search}%")
    return q.execute().data or []


def stats() -> Dict[str, int]:
    sb = get_client()

    def _count(table, **eq):
        try:
            q = sb.table(table).select("id", count="exact")
            for k, v in eq.items():
                q = q.eq(k, v)
            return q.execute().count or 0
        except Exception:  # noqa: BLE001
            return 0

    try:
        admins = sb.table("profiles").select("id", count="exact") \
            .in_("role", ["admin", "super_admin"]).execute().count or 0
    except Exception:  # noqa: BLE001
        admins = 0
    try:
        generated = sb.table("events").select("id", count="exact") \
            .eq("action", "generated").execute().count or 0
    except Exception:  # noqa: BLE001
        generated = 0
    return {
        "users": _count("profiles"),
        "admins": admins,
        "projects": _count("drafts"),
        "proposals_generated": generated,
    }


# ── permission guardrail ──────────────────────────────────────────────
def _can_act(actor: Dict[str, Any], target: Dict[str, Any]) -> Optional[str]:
    """Return an error string if `actor` may NOT act on `target`, else None."""
    if not target:
        return "User not found."
    if target.get("role") == "super_admin":
        return "The super admin account is protected."
    if target.get("id") == actor.get("id"):
        return "You can't perform this action on your own account."
    if target.get("role") == "admin" and actor.get("role") != "super_admin":
        return "Only a super admin can manage another admin."
    return None


# ── mutations (return {ok, ...}) ──────────────────────────────────────
def set_role(actor: Dict[str, Any], target_id: str, new_role: str) -> Dict[str, Any]:
    if new_role not in ("user", "admin"):
        return {"ok": False, "error": "Role must be 'user' or 'admin'."}
    target = get_by_id(target_id)
    err = _can_act(actor, target)
    if err:
        return {"ok": False, "error": err}
    if new_role == "admin" and actor.get("role") != "super_admin":
        return {"ok": False, "error": "Only a super admin can grant the admin role."}
    get_client().table("profiles").update({"role": new_role}).eq("id", target_id).execute()
    return {"ok": True, "role": new_role, "previous_role": target.get("role")}


def set_status(actor: Dict[str, Any], target_id: str, status: str) -> Dict[str, Any]:
    if status not in ("active", "paused"):
        return {"ok": False, "error": "Status must be 'active' or 'paused'."}
    target = get_by_id(target_id)
    err = _can_act(actor, target)
    if err:
        return {"ok": False, "error": err}
    get_client().table("profiles").update({"status": status}).eq("id", target_id).execute()
    return {"ok": True, "status": status}


def ban_user(actor: Dict[str, Any], target_id: str, reason: str = "") -> Dict[str, Any]:
    target = get_by_id(target_id)
    err = _can_act(actor, target)
    if err:
        return {"ok": False, "error": err}
    sb = get_client()
    try:
        sb.auth.admin.update_user_by_id(target_id, {"ban_duration": _BAN_FOREVER})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Auth ban failed: {exc}"}
    sb.table("profiles").update({
        "status": "banned", "banned_at": _now_iso(), "ban_reason": reason or None,
    }).eq("id", target_id).execute()
    return {"ok": True, "status": "banned"}


def unban_user(actor: Dict[str, Any], target_id: str) -> Dict[str, Any]:
    target = get_by_id(target_id)
    err = _can_act(actor, target)
    if err:
        return {"ok": False, "error": err}
    sb = get_client()
    try:
        sb.auth.admin.update_user_by_id(target_id, {"ban_duration": "none"})
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Auth unban failed: {exc}"}
    sb.table("profiles").update({
        "status": "active", "banned_at": None, "banned_until": None, "ban_reason": None,
    }).eq("id", target_id).execute()
    return {"ok": True, "status": "active"}


def delete_user(actor: Dict[str, Any], target_id: str) -> Dict[str, Any]:
    target = get_by_id(target_id)
    err = _can_act(actor, target)
    if err:
        return {"ok": False, "error": err}
    sb = get_client()
    try:
        sb.auth.admin.delete_user(target_id)  # cascades to profiles via FK
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Delete failed: {exc}"}
    try:
        sb.table("profiles").delete().eq("id", target_id).execute()  # in case no cascade
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "email": target.get("email")}
