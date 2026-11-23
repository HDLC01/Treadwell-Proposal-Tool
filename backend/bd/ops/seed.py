"""Load the BD fixture seed (backend/bd/ops/fixture_seed.py) into an EMPTY bd schema.

    python -m bd.ops.seed [--url URL] [--person EMAIL=ROLE ...]

On staging, inside the staging app container (BD_DATABASE_URL is bd_app on the staging Postgres):

    docker compose -f docker-compose.staging.yml exec app \\
        python -m bd.ops.seed --person EMAIL=ROLE --person EMAIL=ROLE

Each --person is a real BD user (on staging: Hanz and Troy, each with the BD role they hold
today: salesperson, assistant, manager, admin or super_admin). They are typed at run time and
never committed; the name shown is made from the address ("first.last@..." -> "First Last").

It refuses, before touching anything:
  * any database that is not staging's (host `db`, database `treadwell`: the staging compose's
    own Postgres, reachable only inside that compose network) or a test database (bd_test_*);
  * a bd schema the migrations have not brought up to date (run the runner first);
  * a bd schema in which ANY table already has a row. It never deletes anything, so it can only
    ever fill an empty schema.
It runs as bd_app (inserts, and moving the id sequences past the seed's ids). The connection
string is never printed.
"""
from __future__ import annotations

import argparse
import re
import sys

ROLES = ("salesperson", "assistant", "manager", "admin", "super_admin")
STAGING_HOST = "db"
STAGING_DBNAME = "treadwell"
_EMAIL = re.compile(r"^[a-z0-9._%+-]+@[a-z0-9-]+(\.[a-z0-9-]+)+$")


def allowed_database(url: str) -> bool:
    """Staging's own database, or a test database."""
    from psycopg import conninfo

    from .. import db

    if not url:
        return False
    if db.is_test_database(url):
        return True
    try:
        d = conninfo.conninfo_to_dict(url)
    except Exception:  # noqa: BLE001  (an unparsable string is not staging)
        return False
    return d.get("host") == STAGING_HOST and d.get("dbname") == STAGING_DBNAME


def _name_from(email: str) -> str:
    local = email.split("@", 1)[0]
    words = [w for w in re.split(r"[._+-]+", local) if w]
    return " ".join(w[:1].upper() + w[1:] for w in words) or local


def parse_people(values) -> list:
    """["email=role", ...] -> [(email, name, role)]. ValueError on a bad entry or a repeat."""
    people, seen = [], set()
    for value in values or ():
        email, sep, role = str(value).partition("=")
        email, role = email.strip().lower(), role.strip().lower()
        if not sep or not _EMAIL.match(email):
            raise ValueError("--person takes EMAIL=ROLE")
        if role not in ROLES:
            raise ValueError("unknown BD role %r (one of %s)" % (role, ", ".join(ROLES)))
        if email in seen:
            raise ValueError("a person is listed twice")
        seen.add(email)
        people.append((email, _name_from(email), role))
    return people


def _tables_with_rows(conn) -> list:
    from psycopg import sql

    tables = [r["t"] for r in conn.execute(
        "select c.relname as t from pg_class c where c.relnamespace = 'bd'::regnamespace"
        " and c.relkind in ('r', 'p') and c.relname <> 'schema_migrations' order by 1").fetchall()]
    return [t for t in tables if conn.execute(
        sql.SQL("select exists (select 1 from {}) as x").format(sql.Identifier("bd", t))).fetchone()["x"]]


def main(argv=None) -> int:
    from .. import config

    ap = argparse.ArgumentParser(prog="python -m bd.ops.seed",
                                 description="Load the made-up BD fixture seed into an empty staging or test bd schema.")
    ap.add_argument("--url", default=None, help="database URL (default: BD_DATABASE_URL); never printed")
    ap.add_argument("--person", action="append", default=[], metavar="EMAIL=ROLE",
                    help="a real BD user to add, with their BD role (repeat for each)")
    args = ap.parse_args(argv)
    url = args.url or config.BD_DATABASE_URL
    if not url:
        print("refusing: no database (set BD_DATABASE_URL or pass --url)", file=sys.stderr)
        return 2
    if not allowed_database(url):
        print("refusing: the seed only goes into staging's database or a test database", file=sys.stderr)
        return 2
    try:
        people = parse_people(args.person)
    except ValueError as exc:
        print("refusing: %s" % exc, file=sys.stderr)
        return 2

    from .. import db, migrate
    from . import fixture_seed

    conn = db.direct(url, autocommit=False)
    try:
        if migrate.ledger_behind(conn):
            print("refusing: the bd schema is not migrated up to date (run python -m bd.migrate first)",
                  file=sys.stderr)
            return 1
        filled = _tables_with_rows(conn)
        if filled:
            print("refusing: the bd schema is not empty (%s have rows); the seed only goes into an empty one"
                  % ", ".join(filled), file=sys.stderr)
            return 1
        counts = fixture_seed.seed(conn, people)
        conn.commit()
    finally:
        conn.close()
    for table, count in counts.items():
        print("%-20s %d" % (table, count))
    print("seeded: %d made-up people, %d given on the command line" % (
        len(fixture_seed.FIXTURE["users"]), len(people)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
