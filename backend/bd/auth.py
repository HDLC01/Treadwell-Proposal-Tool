"""Who is calling a BD route: the proposal tool's verified sign-in, then BD's own people table.

SIGN-IN IS THE TOOL'S (#806). BD's own token check is not carried over. The tool's auth gate
(main._auth_gate) verifies the Supabase Google token on every /api/* request and keeps the verified
identity on the request as `request.state.auth_identity`: {"email", "sub", "name"} (not the token's
claims: no role, aal or amr). BD reads it there
and never looks at the Authorization header itself. Tests sign in by overriding the tool's verify
step (supabase_client.verify_identity), never by switching anything off.

THE BD ROLE IS BD'S. resolve_user(conn, identity) finds the person in bd.users by email (a BD login
is a row there, active or turned off):
  * known and active      -> that row (last_seen_at refreshed at most once a minute)
  * known and inactive    -> 403 "Your BD login is turned off. ..."
  * unknown, but listed in BD_SUPER_ADMIN_EMAIL / BD_ADMIN_EMAILS -> created on this first sign-in
                             as super_admin / admin (bootstrap; both are unset on staging and prod)
  * unknown otherwise     -> 403 "You don't have a BD role. ..."
A proposal-tool admin gets no BD role from being one (Q30): only bd.users decides. The BD API is
guarded by BD role only (Q31).

current_user also checks the migrations ledger in the same checkout: a database behind the code
answers 503 "database not up to date" before anybody is looked up.

Routers use the dependencies:

    from bd.auth import current_user, require_role
    @router.get("/api/bd/contacts")
    def list_contacts(user = Depends(current_user)): ...
    @router.post("/api/bd/contacts")
    def add(user = Depends(require_role("salesperson", "assistant"))): ...   # admins always pass
    @router.post("/api/bd/admin/weekly/run")
    def run(user = Depends(require_role())): ...                              # admin only

`user` is the bd.users row as a dict: id, email, name, role, active, last_seen_at, ...
"""
from __future__ import annotations

import logging
import re

from fastapi import Depends, Request

from . import bizdate, config, db, ledger
from .errors import ApiError

log = logging.getLogger("bd.auth")

ROLES = ("salesperson", "assistant", "manager", "admin", "super_admin")
ADMIN_ROLES = ("admin", "super_admin")
_SEEN_REFRESH_SECONDS = 60

NOT_SIGNED_IN = "Sign in with your Treadwell Google account."
NO_BD_ROLE = "You don't have a BD role. Ask a BD admin to add you."
TURNED_OFF = "Your BD login is turned off. Ask a BD admin to turn it back on."
NOT_UP_TO_DATE = "The BD CRM's database is not up to date. Try again after the next update."


class AuthError(ApiError):
    """401 (who are you?) or 403 (you may not); the message is safe to show."""

    def __init__(self, status: int, message: str):
        super().__init__(status, message)


# ── the person ───────────────────────────────────────────────────────────────────────────────
def name_of_email(email: str) -> str:
    """"pat.lee@example.com" -> "Pat Lee" (BD's shared.js nameOf)."""
    local = str(email).split("@")[0]
    words = [w for w in re.split(r"[._-]+", local) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or str(email)


def bootstrap_role(email: str) -> str | None:
    """The BD role a not-yet-known email gets on first sign-in, or None (not allowed in)."""
    email = (email or "").strip().lower()
    if config.BD_SUPER_ADMIN_EMAIL and email == config.BD_SUPER_ADMIN_EMAIL:
        return "super_admin"
    if email in config.BD_ADMIN_EMAILS:
        return "admin"
    return None


USER_COLUMNS = "id, email, name, role, active, auth_sub, last_seen_at, created_at"


def resolve_user(conn, identity: dict) -> dict:
    """The bd.users row for this verified identity (see the module docstring for the rules)."""
    email = str(identity.get("email") or "").strip().lower()
    if not email:
        raise AuthError(401, NOT_SIGNED_IN)
    sub = str(identity.get("sub") or "") or None
    row = conn.execute("select " + USER_COLUMNS + " from users where email = %s", (email,)).fetchone()
    if row is None:
        role = bootstrap_role(email)
        if role is None:
            raise AuthError(403, NO_BD_ROLE)
        name = str(identity.get("name") or "").strip() or name_of_email(email)
        conn.execute(
            "insert into users (email, name, role, active, auth_sub, last_seen_at)"
            " values (%s, %s, %s, true, %s, bd_now()) on conflict (email) do nothing",
            (email, name, role, sub))
        row = conn.execute("select " + USER_COLUMNS + " from users where email = %s", (email,)).fetchone()
        log.info("first sign-in: user %s bootstrapped as %s", row["id"], row["role"])
    if not row["active"]:
        raise AuthError(403, TURNED_OFF)
    now = bizdate.now_central()
    seen = row["last_seen_at"]
    if seen is None or abs((now - seen).total_seconds()) >= _SEEN_REFRESH_SECONDS or (sub and not row["auth_sub"]):
        row = conn.execute(
            "update users set last_seen_at = bd_now(), auth_sub = coalesce(auth_sub, %s)"
            " where id = %s returning " + USER_COLUMNS, (sub, row["id"])).fetchone()
    return dict(row)


def signed_in_identity(request: Request) -> dict:
    """The identity the tool's auth gate verified for this request. 401 when there is none (a
    public path, or a request that never passed the gate)."""
    identity = getattr(request.state, "auth_identity", None)
    if not isinstance(identity, dict) or not identity.get("email"):
        raise AuthError(401, NOT_SIGNED_IN)
    return identity


def sign_in_domain() -> str:
    """The email domain the proposal tool's sign-in lets in (supabase_client.ALLOWED_DOMAIN, the
    gate's rule, read at call time). BD's People table adds a login only on it (#809). The one tool
    setting BD reads, read-only and only here (bd/config.py; tests/test_bd_config.py)."""
    import supabase_client

    return str(supabase_client.ALLOWED_DOMAIN or "").strip().lower().lstrip("@")


def current_user(request: Request) -> dict:
    """FastAPI dependency: the signed-in person's active BD login (a dict). One checkout checks the
    ledger, then looks the person up. Cached on the request."""
    user = getattr(request.state, "bd_user", None)
    if user is not None:
        return user
    identity = signed_in_identity(request)
    with db.connect() as conn:
        if ledger.ledger_behind(conn):
            raise ApiError(503, NOT_UP_TO_DATE, code="unavailable")
        user = resolve_user(conn, identity)
    request.state.bd_user = user
    return user


# ── roles ────────────────────────────────────────────────────────────────────────────────────
def is_admin(user) -> bool:
    return bool(user) and user.get("role") in ADMIN_ROLES


def has_role(user, *roles) -> bool:
    """Admins and super admins pass every check (contract: "A route marked salesperson is also
    open to admin"); everyone else needs one of `roles`."""
    return is_admin(user) or (bool(user) and user.get("role") in roles)


def require_role(*roles, message: str = "Your role can't do that."):
    """A dependency that returns the user when they hold one of `roles` (or are an admin), else
    403. `require_role()` with no roles = admins only."""
    def _check(user: dict = Depends(current_user)) -> dict:
        if not has_role(user, *roles):
            raise AuthError(403, message)
        return user
    _check.__name__ = "require_" + ("_".join(roles) or "admin")
    return _check


def can(user) -> dict:
    """/api/bd/me's `can` (api-contract.md table). The server still checks every call."""
    role = user.get("role") if user else None
    a = role in ADMIN_ROLES
    return {
        "send": a or role == "salesperson",
        "analytics": a or role == "manager",
        "admin": a,
        "admin_area": a or role == "assistant",
        "import": a or role in ("assistant", "salesperson"),
        "run_batch": a,
        "week": a or role in ("salesperson", "manager"),
        # Looks at any salesperson's week (This Week's "Whose week?" picker); a salesperson sees only
        # their own. This Week and the contact page also show the week's priority score by it.
        "pick_owner": a or role == "manager",
        # The contact page and Add contact (#808). Each key is what one of BD's route checks lets in,
        # so the pages show a control only to a person the route will not refuse.
        # Adds a BD contact (POST /api/bd/contacts).
        "add_contact": a or role in ("salesperson", "assistant"),
        # Edits a contact's details, confirms, archives, adds a note, flags "not the right person".
        "edit_contact": a or role in ("salesperson", "assistant"),
        # Clears a possible-duplicate flag (PATCH {duplicate_of: null}).
        "clear_duplicate": a or role == "assistant",
        # Changes how often to follow up: every role (a manager may change only this). The contact
        # page reads cadence WITHOUT edit_contact as "only the cadence sheet", so a change to either
        # key changes who gets that sheet (test_bd_contact_page's manager case).
        "cadence": a or role in ("salesperson", "assistant", "manager"),
        # Deletes a logged entry, or changes one somebody else logged.
        "manage_entries": a,
        # Adds a BD admin, or changes an admin's login (#809, Q29): the super admin's alone
        # (refuse_new_login / refuse_login_change below). BD's Admin page offers the admin roles, and
        # an admin's row, only to this person, and tells a plain admin why the row is locked.
        "manage_admins": role == "super_admin",
    }


# ── who may change a BD login (Q29) ──────────────────────────────────────────────────────────
ONLY_SUPER_ADDS_ADMIN = "Only a super admin can add an admin."
ONLY_SUPER_CHANGES_ADMIN = "Only a super admin can change an admin."
NOT_YOUR_OWN = "You can't change your own role or sign-in."


def refuse_new_login(me: dict, role) -> str | None:
    """Why `me` may not add a BD login with this role, or None. An admin a plain admin made could
    never be changed again (only a super admin changes an admin), so only a super admin adds one."""
    if role in ADMIN_ROLES and (me or {}).get("role") != "super_admin":
        return ONLY_SUPER_ADDS_ADMIN
    return None


def refuse_login_change(me: dict, target: dict, changes: dict) -> str | None:
    """Why `me` may not make `changes` ({role?, active?, name?}) to `target`'s BD login, or None.
    Nobody changes their OWN role or sign-in (their own name is fine). Changing a login that is an
    admin's, or making someone an admin, is the super admin's alone."""
    me = me or {}
    self_edit = target.get("id") == me.get("id")
    changes_role = "role" in changes and changes["role"] != target.get("role")
    changes_active = "active" in changes and changes["active"] != target.get("active")
    if self_edit and (changes_role or changes_active):
        return NOT_YOUR_OWN
    if not self_edit and (is_admin(target) or changes.get("role") in ADMIN_ROLES) \
            and me.get("role") != "super_admin":
        return ONLY_SUPER_CHANGES_ADMIN
    return None
