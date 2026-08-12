"""How far back we pull BasisBoard data — one window, for the whole company.

Hanz, 2026-08-12: "this is for the analytics. We need to create a date range on when we will be
getting data from the basisboard API because the analytics will eventually be moved to this
proposal tool using the data from here", then "we need a date pciker like the custom date in the
analytics for when it pulls data". Asked whether this should be per-person or org-wide, he chose
one shared window.

ORG-WIDE, NOT PER-VIEWER, is the whole design. The Analytics page already has its own from/to
filter for looking at a slice, and that stays exactly as it is — client-side, instant, personal.
This is the different question underneath it: which bids we hold at all. Everyone reading the
dashboard has to be reading the same dataset, or two people quote different win rates for the same
month and neither is wrong.

A FILE, not a database table and not an environment variable. Staff edit it from the Analytics
page, so an env var (a redeploy and somebody with SSH) is out; and the analytics dataset itself
already lives on this volume as a snapshot, so the setting that shapes it belongs beside it rather
than in a database the analytics path otherwise never touches.

FAIL-OPEN ON READ, LOUD ON WRITE. An unreadable or garbled file reads as "no window" — all-time,
which is exactly today's behaviour, so a corrupt byte costs nothing but a wider pull. A failed
WRITE is raised: an org setting that "saved" into one container's memory and nowhere else is worse
than one that refused, because the person who set it has no way to find out.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("treadwell.pull_window")

# Beside the analytics snapshot on the data volume, for the reason in the module docstring.
_DATA_DIR = Path(os.environ.get("DRAFTS_DB_PATH", "/app/data/drafts.db")).parent
_FILE = _DATA_DIR / "analytics_pull_window.json"

_LOCK = threading.Lock()

OPEN: Dict[str, Any] = {"from": None, "to": None, "updated_at": None, "updated_by": None}


class PullWindowError(ValueError):
    """The window a caller asked for is not a window."""


class PullWindowWriteError(RuntimeError):
    """The window could not be persisted, so nothing else may act as though it was."""


def _day(value: Any) -> Optional[str]:
    """`YYYY-MM-DD`, or None for empty. Anything else raises.

    Parsed rather than pattern-matched: "2026-02-30" matches every plausible regex and is not a
    day. A window built on it would silently include or exclude whatever the comparison happened
    to do with the string."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        d = _dt.date.fromisoformat(text)
    except ValueError as exc:
        raise PullWindowError("expected a date as YYYY-MM-DD, got %r" % text) from exc
    return d.isoformat()


def validate(frm: Any, to: Any) -> Dict[str, Optional[str]]:
    """The single authority on what a window may be. Returns the normalised pair."""
    f, t = _day(frm), _day(to)
    if f and t and f > t:
        raise PullWindowError("the window starts after it ends: %s → %s" % (f, t))
    return {"from": f, "to": t}


def _read() -> Dict[str, Any]:
    if not _FILE.is_file():
        return dict(OPEN)
    try:
        raw = json.loads(_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("not an object")
        # Validate on the way OUT as well. A hand-edited file with from > to would otherwise
        # exclude every row and read as "the org has no bids".
        pair = validate(raw.get("from"), raw.get("to"))
        return {"from": pair["from"], "to": pair["to"],
                "updated_at": raw.get("updated_at") or None,
                "updated_by": raw.get("updated_by") or None}
    except Exception as exc:  # noqa: BLE001 — a bad file must widen the pull, never break a page
        log.warning("analytics pull window unreadable (%s); treating as all-time", exc)
        return dict(OPEN)


def get() -> Dict[str, Any]:
    """The current window. Always a full dict; all-time when unset or unusable."""
    with _LOCK:
        return _read()


def set(frm: Any, to: Any, by: str = "") -> Dict[str, Any]:  # noqa: A001 — the verb reads right
    """Persist a window and return it. Raises PullWindowError / PullWindowWriteError."""
    pair = validate(frm, to)
    out = {"from": pair["from"], "to": pair["to"],
           "updated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "updated_by": (by or "").strip() or None}
    with _LOCK:
        try:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            tmp = _FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(out), encoding="utf-8")
            tmp.replace(_FILE)               # atomic: a reader sees the old window or the new one
        except Exception as exc:  # noqa: BLE001
            raise PullWindowWriteError(str(exc)) from exc
    log.info("analytics pull window set to %s → %s by %s",
             out["from"] or "(all time)", out["to"] or "(today)", out["updated_by"] or "?")
    return out


def is_open(win: Optional[Dict[str, Any]] = None) -> bool:
    """True when the window bounds nothing — the default, and today's behaviour."""
    w = get() if win is None else win
    return not w.get("from") and not w.get("to")
