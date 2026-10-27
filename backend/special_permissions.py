"""Special permissions: one admin-only ability granted to one named person.

Hanz, 2026-10-27, on the Admin page's "What each role can see" matrix: a plain member sometimes
needs ONE thing only admins can do (Marisol editing an item's price breaks, bulk cost and coverage
basis) and making her an admin to get it hands her the users table, the bans and the tab policy
too. So: "a list of names and then the checkboxes".

SAME SHAPE AND POSTURE AS nav_access.py. A file on the data volume, not a table, so the recovery
for a grant given by mistake is one command with no SQL:

    docker exec treadwell-proposal-tool rm -f /app/data/special_permissions.json

An absent, empty or garbled file means NOBODY has a grant - which is exactly the behaviour before
this module existed, because every route these keys open was admin-only. Unlike nav_access, the
fail-safe direction here is CLOSED: a grant widens access, so an unreadable file must not.

A failed WRITE raises (SpecialPermissionsWriteError), for nav_access's reason: an admin who thinks
they gave or took away an ability and did not has no way to find out.

ONLY THE KEYS IN `GRANTS` EXIST. Users, roles, bans, the tab policy, these grants themselves, the
digest, health and stats stay admin-only and are not grantable on purpose: each of them is either a
way to grant yourself more, or a way to lock somebody else out.
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

log = logging.getLogger("treadwell.special_permissions")

_DATA_DIR = Path(os.environ.get("DRAFTS_DB_PATH", "/app/data/drafts.db")).parent
_FILE = _DATA_DIR / "special_permissions.json"

_LOCK = threading.Lock()
_VERSION = 1

# (key, label, description) - ordered; the Admin page draws one checkbox column per entry, in order.
GRANTS: Tuple[Tuple[str, str, str], ...] = (
    ("items_pricing", "Items: price breaks, bulk cost, coverage basis",
     "Edit the admin-only fields on an item in Items and Assemblies: price breaks, bulk cost "
     "and coverage basis."),
    ("library_lists", "Vendors, divisions, units and labor rates",
     "Add, edit and remove the vendors, divisions, units and labor rates everyone picks from, "
     "and the labor calculator lines."),
    ("markup", "Markup rules",
     "Add, change and delete markup rules on the Markup page."),
    ("condition_defaults", "Condition defaults",
     "Change the default values the job conditions start from."),
    ("notify_recipients", "Notification recipients",
     "Add, remove and switch the team members on the Notification Sending roster, for everyone."),
    ("delete_projects", "Delete projects",
     "Move a project off the board to Trash (restorable from the Trash page)."),
)
KEYS: Tuple[str, ...] = tuple(k for k, _l, _d in GRANTS)

EMPTY: Dict[str, Any] = {"version": _VERSION, "grants": {}, "updated_at": None, "updated_by": None}


class SpecialPermissionsWriteError(RuntimeError):
    """The grants could not be persisted, so nothing may act as though they were."""


def catalog() -> List[Dict[str, str]]:
    """The grantable abilities, for the Admin page's column headers."""
    return [{"key": k, "label": label, "description": desc} for k, label, desc in GRANTS]


def _norm_email(value: Any) -> str:
    return str(value or "").strip().lower()


def sanitize(grants: Any) -> Dict[str, List[str]]:
    """The one authority on what a grants map may hold. Never raises; drops what it cannot use.

    Blank emails, unknown keys and duplicates go; an email with nothing left is dropped entirely.
    Keys come back in GRANTS order so a saved file is stable regardless of tick order.
    """
    out: Dict[str, List[str]] = {}
    if not isinstance(grants, dict):
        return out
    for email, keys in grants.items():
        who = _norm_email(email)
        if not who or isinstance(keys, (str, bytes)) or not isinstance(keys, Iterable):
            continue
        wanted = {str(k or "").strip() for k in keys}
        keep = [k for k in KEYS if k in wanted]
        if keep:
            merged = out.setdefault(who, [])
            for k in keep:
                if k not in merged:
                    merged.append(k)
            out[who] = [k for k in KEYS if k in merged]
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
    """The keys this person holds, in GRANTS order. [] for anyone not listed."""
    who = _norm_email(email)
    if not who:
        return []
    return list(load()["grants"].get(who, []))


def has(email: Any, key: str) -> bool:
    return key in KEYS and key in grants_for(email)
