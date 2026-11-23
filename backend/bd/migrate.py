"""The BD schema's migrations runner: apply backend/bd/migrations/NNN_*.sql in order, each once.

    python -m bd.migrate                 # asks for the ADMIN database URL (typed, never stored)
    python -m bd.migrate --status        # list applied / pending, change nothing
    python -m bd.migrate --url URL       # the URL on the command line instead: a database on THIS
                                         # machine only (tests, local dev); refused for any other

    migrate.migrate(url) -> [names applied]
    migrate.ledger_behind(conn) -> bool      # the routes' check (lives in bd/ledger.py)

IT NEVER RUNS AT APP STARTUP. Schema changes are made by the database's admin login, by hand on
prod on Hanz's go, and on staging by the generated BD part of backend/staging/schema_pg.sql (which
applies the same files under the same lock; backend/bd/ops/staging_schema.py writes it). The app
connects as bd_app, which cannot change the schema; it only reads the ledger (bd/ledger.py) to know
whether it is behind the code (tests/test_bd_migrate.py proves nothing in the app imports this module).

How it works (BD's own runner, moved into schema bd):
  * bd.schema_migrations (name text primary key, applied_at timestamptz) is the LEDGER.
  * Files are taken in LEXICAL order of their names (001_schema.sql, 002_...). Only names that
    match NNN_*.sql count; anything else in the folder (grants.sql) is not a migration.
  * Each file runs in ITS OWN transaction with its ledger row and the grants, so a file that fails
    leaves nothing half-applied and is tried again next time, and no committed state ever lacks
    the privilege model.
  * A session advisory lock makes two runs (or a run and a staging deploy) take turns.
  * Then grants.sql is applied once more, so a run with nothing pending still repairs privileges.
  * Applying again changes nothing. An applied file is never re-run, even if edited: a change to
    the schema is a NEW file.
  * The connection string is never printed or logged.
"""
from __future__ import annotations

import argparse
import getpass
import pathlib
import sys

# The read-only half (which files exist, which the ledger lacks) lives in ledger.py, so the app can
# ask "is the database behind?" without importing this runner. Re-exported here for the runner's
# callers and tests.
from .ledger import (  # noqa: F401
    MIGRATIONS_DIR,
    _applied,
    _tuples,
    ledger_behind,
    migration_files,
    pending,
)

GRANTS_FILE = MIGRATIONS_DIR / "grants.sql"
SCHEMA = "bd"
LEDGER = "bd.schema_migrations"
# Any constant works; it only has to be the same for every runner and for the staging schema file.
# Advisory locks are per database, so this never blocks a run against another database.
LOCK_KEY = 0x0BDC0001

# Run under the lock before anything else, by the runner and by the staging schema file alike.
BOOTSTRAP_SQL = (
    "create schema if not exists bd;\n"
    "create table if not exists bd.schema_migrations (\n"
    "  name        text primary key,\n"
    "  applied_at  timestamptz not null default now()\n"
    ");\n"
)


def read_sql(path: pathlib.Path) -> str:
    """A file's SQL with its line endings made LF, so a Windows checkout sends what CI sends."""
    return pathlib.Path(path).read_text(encoding="utf-8").replace("\r\n", "\n")


def grants_sql() -> str:
    return read_sql(GRANTS_FILE)


def _has_bd_app(conn) -> bool:
    return bool(_tuples(conn, "select 1 from pg_roles where rolname = 'bd_app'"))


def migrate(url: str, directory: pathlib.Path = MIGRATIONS_DIR, log=None) -> list:
    """Apply every pending migration, then the grants. Returns the names applied (empty when up to
    date). `url` is the ADMIN login, never bd_app."""
    import psycopg

    if not url:
        raise ValueError("migrate() needs the admin database URL")
    grants = grants_sql()
    done_now = []
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("select pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            with conn.transaction():
                conn.execute(BOOTSTRAP_SQL)
            have = _applied(conn)
            for path in migration_files(directory):
                if path.name in have:
                    continue
                with conn.transaction():
                    # No parameters: the file is sent as is (several statements, $$ bodies, any %).
                    conn.execute(read_sql(path))
                    conn.execute("insert into bd.schema_migrations (name) values (%s)", (path.name,))
                    conn.execute(grants)
                done_now.append(path.name)
                if log:
                    log("applied %s" % path.name)
            with conn.transaction():
                conn.execute(grants)
            if log and not _has_bd_app(conn):
                log("bd_app does not exist yet: its grants and policies were skipped. "
                    "Create the login, then run this again.")
        finally:
            conn.execute("select pg_advisory_unlock(%s)", (LOCK_KEY,))
    return done_now


def status(url: str, directory: pathlib.Path = MIGRATIONS_DIR) -> list:
    """[(name, applied?)] for every migration file. Changes nothing."""
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        todo = set(pending(conn, directory))
    return [(p.name, p.name not in todo) for p in migration_files(directory)]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bd.migrate",
                                 description="Apply the BD CRM's SQL migrations to schema bd.")
    ap.add_argument("--status", action="store_true", help="list applied and pending, change nothing")
    ap.add_argument("--url", help="the ADMIN database URL (default: asked for, never echoed or stored)")
    args = ap.parse_args(argv)
    if args.url:
        from . import db

        if not db.is_local_url(args.url):
            print("refusing: --url is only for a database on this machine (tests, local dev), because "
                  "it puts the password in shell history. Leave it out and type the URL when asked.",
                  file=sys.stderr)
            return 2
    url = args.url or getpass.getpass("Admin database URL (not echoed): ").strip()
    if not url:
        print("no database URL given", file=sys.stderr)
        return 2
    if args.status:
        for name, ok in status(url):
            print(("applied  " if ok else "pending  ") + name)
        return 0
    names = migrate(url, log=print)
    if not names:
        print("up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
