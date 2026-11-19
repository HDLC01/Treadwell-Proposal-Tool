"""The migrations ledger, read-only: which migration files exist, and which the database lacks.

    from bd import ledger
    ledger.ledger_behind(conn) -> bool     # the routes' "database not up to date" check
    ledger.pending(conn) -> [names]

Split from migrate.py (the runner) so the app can ask "is the database behind the code?" without
importing the runner: nothing the app imports can change the schema (tests/test_bd_migrate.py
proves the app never loads bd.migrate). Every query here is a SELECT, so bd_app can run it.
"""
from __future__ import annotations

import pathlib
import re

MIGRATIONS_DIR = pathlib.Path(__file__).resolve().parent / "migrations"
_NAME = re.compile(r"^\d{3}_[A-Za-z0-9_\-]+\.sql$")


def migration_files(directory: pathlib.Path = MIGRATIONS_DIR) -> list:
    """The migration files, in the order they apply."""
    return sorted((p for p in pathlib.Path(directory).glob("*.sql") if _NAME.match(p.name)),
                  key=lambda p: p.name)


def _tuples(conn, sql: str) -> list:
    """Rows as tuples whatever row factory the connection has (the pool's is dict rows)."""
    from psycopg.rows import tuple_row

    return conn.cursor(row_factory=tuple_row).execute(sql).fetchall()


def _applied(conn) -> set:
    return {r[0] for r in _tuples(conn, "select name from bd.schema_migrations")}


def pending(conn, directory: pathlib.Path = MIGRATIONS_DIR) -> list:
    """Names of the migration files the ledger lacks, in order. Read-only, so bd_app can call it:
    a database with no ledger at all has every file pending."""
    present = _tuples(conn, "select to_regclass('bd.schema_migrations')")[0][0] is not None
    have = _applied(conn) if present else set()
    return [p.name for p in migration_files(directory) if p.name not in have]


def ledger_behind(conn, directory: pathlib.Path = MIGRATIONS_DIR) -> bool:
    """True when the code holds a migration the database has not applied (the routes answer 503
    "database not up to date"). A ledger AHEAD of the code (an older image) is not behind."""
    return bool(pending(conn, directory))
