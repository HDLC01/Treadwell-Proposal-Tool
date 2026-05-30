"""
Draft persistence — SQLite-backed, so a half-filled project survives a
tab close AND can be reopened on another device via its draft URL.

Design:
  - One row per draft, keyed by a client-generated UUID (the `d` query
    param in the URL: proposals.wetreadwell.com/?d=<uuid>).
  - `data` is the full sessionStorage state blob as JSON text. We don't
    normalise it into columns — the field set is large + evolving, and
    we only ever read/write the whole blob.
  - Auto-saved from the frontend every few seconds as the user types.

DB file location is configurable via DRAFTS_DB_PATH so Docker can point
it at a persistent volume (/app/data/drafts.db). Defaults to a `data/`
folder next to this file for local dev.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Resolve the DB path. In Docker we set DRAFTS_DB_PATH=/app/data/drafts.db
# and mount a volume there; locally it lands in backend/data/drafts.db.
_DB_PATH = Path(
    os.environ.get("DRAFTS_DB_PATH")
    or (Path(__file__).parent / "data" / "drafts.db")
)

# SQLite connections aren't safe to share across threads by default; a
# process-wide lock keeps the writes serialized. Volume is tiny + writes
# are infrequent (debounced ~3s), so a single lock is plenty.
_LOCK = threading.Lock()
_conn: Optional[sqlite3.Connection] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    """Create the data dir + table if missing. Called once at app start."""
    global _conn
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    _conn.execute(
        """
        CREATE TABLE IF NOT EXISTS drafts (
            id          TEXT PRIMARY KEY,
            data        TEXT NOT NULL,
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        )
        """
    )
    _conn.commit()


def save_draft(draft_id: str, data: Dict[str, Any]) -> Dict[str, str]:
    """Upsert a draft. Returns {id, updated_at}."""
    if _conn is None:
        init_db()
    blob = json.dumps(data, ensure_ascii=False)
    now = _now_iso()
    with _LOCK:
        # Preserve created_at on update via COALESCE against the existing row.
        _conn.execute(
            """
            INSERT INTO drafts (id, data, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                data = excluded.data,
                updated_at = excluded.updated_at
            """,
            (draft_id, blob, now, now),
        )
        _conn.commit()
    return {"id": draft_id, "updated_at": now}


def load_draft(draft_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a draft by id. Returns {id, data, created_at, updated_at} or None."""
    if _conn is None:
        init_db()
    with _LOCK:
        row = _conn.execute(
            "SELECT id, data, created_at, updated_at FROM drafts WHERE id = ?",
            (draft_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "data": json.loads(row[1]),
        "created_at": row[2],
        "updated_at": row[3],
    }


def delete_draft(draft_id: str) -> bool:
    """Remove a draft (called on 'Start a new project'). Returns True if existed."""
    if _conn is None:
        init_db()
    with _LOCK:
        cur = _conn.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))
        _conn.commit()
        return cur.rowcount > 0
