"""Special permissions: one TAB granted to one named person.

Hanz, 2026-10-27, on the Admin page's "What each role can see" matrix: a plain member sometimes
needs something only admins can do (Marisol editing an item's price breaks, bulk cost and coverage
basis) and making her an admin to get it hands her the users table, the bans and the tab policy
too. So: "a list of names and then the checkboxes".

ONE CHECKBOX PER TAB (Hanz, the same day: "why is special permissions only linked to items and
assemblies? It should be for the whole tab as well."). The first cut granted six separate abilities;
this replaces them. Ticking a tab for a person gives them:
  (a) THE TAB: it shows in their sidebar and its page opens even when their ROLE is unticked for it
      on the matrix - main.py subtracts these from the role's denied tabs for that one person; and
  (b) EVERY ADMIN-ONLY EDIT INSIDE IT: each grantable route names its tab in _require_grant.

THE KEYS ARE nav_access.TABS hrefs, every tab except the Admin page itself, in the matrix's order and
with its labels. Users, roles, bans, the tab policy, these grants themselves, the digest, health and
stats stay admin-only and are not grantable on purpose: each of them is either a way to grant
yourself more, or a way to lock somebody else out.

SAME SHAPE AND POSTURE AS nav_access.py. A file on the data volume, not a table, so the recovery
for a grant given by mistake is one command with no SQL:

    docker exec treadwell-proposal-tool rm -f /app/data/special_permissions.json

An absent, empty or garbled file means NOBODY has a grant - which is exactly the behaviour before
this module existed. Unlike nav_access, the fail-safe direction here is CLOSED: a grant widens
access, so an unreadable file must not.

A failed WRITE raises (SpecialPermissionsWriteError), for nav_access's reason: an admin who thinks
they gave or took away a tab and did not has no way to find out.

A FILE SAVED BY THE SIX-ABILITY VERSION STILL WORKS: sanitize() reads each old ability key as the tab
it lived on (LEGACY_KEYS), so a grant ticked on staging before this change keeps its meaning.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Dict, List, Tuple

import atomic_json
import nav_access

log = logging.getLogger("treadwell.special_permissions")

_DATA_DIR = Path(os.environ.get("DRAFTS_DB_PATH", "/app/data/drafts.db")).parent
_FILE = _DATA_DIR / "special_permissions.json"

_LOCK = threading.Lock()
_VERSION = 2

# Never grantable: the page where users, roles, the tab policy and these grants are edited.
NOT_GRANTABLE: Tuple[str, ...] = ("/admin.html",)

# The grantable tabs, in the matrix's own order. The Admin page draws one checkbox column per entry.
KEYS: Tuple[str, ...] = tuple(h for h in nav_access.TABS if h not in NOT_GRANTABLE)

# Where each route group's admin-only edits live: the tab whose grant opens them. main.py passes the
# tab href to _require_grant; this is the one place that says which group belongs to which tab.
LIBRARY = "/library.html"          # item price breaks / bulk cost / coverage basis, the lists,
                                   # labor lines and calculator, condition defaults
MARKUP = "/markup.html"            # markup rules
NOTIFICATIONS = "/notifications.html"  # the Notification Sending roster
PROJECTS = "/portal.html"          # Delete a project (the Direct Projects board's drawer)

# The six abilities of the first cut, read as the tab each one lived on.
LEGACY_KEYS: Dict[str, str] = {
    "items_pricing": LIBRARY,
    "library_lists": LIBRARY,
    "condition_defaults": LIBRARY,
    "markup": MARKUP,
    "notify_recipients": NOTIFICATIONS,
    "delete_projects": PROJECTS,
}

EMPTY: Dict[str, Any] = {"version": _VERSION, "grants": {}, "updated_at": None, "updated_by": None}


class SpecialPermissionsWriteError(RuntimeError):
    """The grants could not be persisted, so nothing may act as though they were."""


def catalog() -> List[Dict[str, str]]:
    """The grantable tabs, for the Admin page's column headers: the tab's label, its href as key."""
    return [{"key": href, "label": nav_access.TABS[href]["label"], "href": href} for href in KEYS]


def _norm_email(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_key(value: Any) -> str:
    """A stored key as a grantable tab href, or "" - old ability keys and moved hrefs included."""
    raw = str(value or "").strip()
    if raw in LEGACY_KEYS:
        return LEGACY_KEYS[raw]
    href = raw.lower()
    if href and not href.startswith("/"):
        href = "/" + href
    href = nav_access.LEGACY_HREFS.get(href, href)
    return href if href in KEYS else ""


def sanitize(grants: Any) -> Dict[str, List[str]]:
    """The one authority on what a grants map may hold. Never raises; drops what it cannot use.

    Blank emails, unknown keys and duplicates go; an email with nothing left is dropped entirely.
    Old ability keys become their tab. Keys come back in KEYS order so a saved file is stable
    regardless of tick order.
    """
    out: Dict[str, List[str]] = {}
    if not isinstance(grants, dict):
        return out
    for email, keys in grants.items():
        who = _norm_email(email)
        if not who or isinstance(keys, (str, bytes)) or not isinstance(keys, Iterable):
            continue
        wanted = {_norm_key(k) for k in keys} | set(out.get(who, []))
        keep = [k for k in KEYS if k in wanted]
        if keep:
            out[who] = keep
    return out


def _read() -> Dict[str, Any]:
    if not _FILE.is_file():
        return dict(EMPTY, grants={})
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        return {"version": _VERSION, "grants": sanitize(raw.get("grants")),
                "updated_at": raw.get("updated_at") or None,
                "updated_by": raw.get("updated_by") or None}
    except Exception as exc:  # noqa: BLE001 - a bad file grants nothing; it never breaks a page
        log.warning("special permissions unreadable (%s); nobody has a grant", exc)
        return dict(EMPTY, grants={})


def load() -> Dict[str, Any]:
    """The whole store. Always a full dict; nobody granted anything when unset or unusable."""
    with _LOCK:
        return _read()


def save(grants: Any, by: str = "") -> Dict[str, Any]:
    """Persist a grants map and return the stored copy. Raises SpecialPermissionsWriteError."""
    clean = sanitize(grants)
    out = {"version": _VERSION, "grants": clean,
           "updated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "updated_by": (by or "").strip() or None}
    with _LOCK:
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            atomic_json.write_json(_FILE, out, make_parent=False)
        except Exception as exc:  # noqa: BLE001
            raise SpecialPermissionsWriteError(str(exc)) from exc
    log.info("special permissions set by %s: %s", out["updated_by"] or "?",
             json.dumps(clean) if clean else "(none)")
    return out


def grants_for(email: Any) -> List[str]:
    """The tab hrefs this person holds, in KEYS order. [] for anyone not listed."""
    who = _norm_email(email)
    if not who:
        return []
    return list(load()["grants"].get(who, []))


def has(email: Any, key: str) -> bool:
    return key in KEYS and key in grants_for(email)
