"""
Audit trail — one JSON object per line, recording authenticated state-changing
actions + sensitive-data reads (who deleted this / who viewed these contacts).

Sinks:
  - ALWAYS stdout, prefixed "AUDIT " so `docker logs` is greppable.
  - ADDITIONALLY a RotatingFileHandler at <DATA_DIR>/audit.log when a writable
    persistent dir exists (the Docker volume at /app/data; see docker-compose.yml).

Additive + safe: callers wrap audit_log() in try/except (see main.py middleware)
so this can never alter a response or break a request. No request bodies, query
strings, headers, or tokens are ever logged — only method + path + user + status
+ ip.
"""
from __future__ import annotations

import json
import logging
import logging.handlers
import os
from pathlib import Path

# DATA_DIR = the persistent volume parent of the SQLite drafts DB
# (DRAFTS_DB_PATH=/app/data/drafts.db in docker-compose). Falls back to /app/data.
_DB_PATH = os.environ.get("DRAFTS_DB_PATH") or "/app/data/drafts.db"
DATA_DIR = Path(_DB_PATH).parent

_logger = logging.getLogger("audit")
_logger.setLevel(logging.INFO)
_logger.propagate = False  # don't double-log through the root handler

# Plain message formatter — the record itself is already a JSON string.
_fmt = logging.Formatter("AUDIT %(message)s")

# Sink 1: always stdout, so `docker logs | grep AUDIT` works.
_stream = logging.StreamHandler()
_stream.setFormatter(_fmt)
_logger.addHandler(_stream)

# Sink 2: rotating file on the persistent volume, only if it's writable.
try:
    if DATA_DIR.is_dir() and os.access(DATA_DIR, os.W_OK):
        _fh = logging.handlers.RotatingFileHandler(
            DATA_DIR / "audit.log", maxBytes=5_000_000, backupCount=5,
            encoding="utf-8",
        )
        _fh.setFormatter(logging.Formatter("%(message)s"))  # file = pure JSONL
        _logger.addHandler(_fh)
except Exception:  # noqa: BLE001 — file sink is best-effort; stdout still works
    pass


def audit_log(record: dict) -> None:
    """Emit one audit record as a single JSON line to every configured sink."""
    _logger.info(json.dumps(record, ensure_ascii=False, default=str))
