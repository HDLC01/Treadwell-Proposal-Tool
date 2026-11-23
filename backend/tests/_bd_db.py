"""BD's Postgres helpers for tests (#805). Not a test file: the BD fixtures in _bd_conftest.py and
the schema tests (test_bd_migrate.py, test_bd_schema_privileges.py, test_bd_staging_schema.py)
build on these.

THE TEST SERVER. BD_TEST_DATABASE_URL is an ADMIN url (a superuser on a THROWAWAY Postgres 16,
e.g. a local container or CI's service). Every test database is created on it as bd_test_<...>
and dropped afterwards. Unset: the BD database tests SKIP locally and FAIL on CI. A URL whose host
is not this machine, or a server that looks like Supabase, FAILS the run whatever the machine: the
roles below have passwords that sit in this public repo, and they stay on the server.

ROLES ARE CLUSTER-WIDE, databases are not. xdist workers share one server, so:
  * roles the tests only ever CREATE (bd_app, the bd_app-like test login, and the staging file's
    service_role and authenticator) are made with a duplicate-tolerant statement;
  * the roles a test creates AND drops (anon, authenticated, a stray login) are made and dropped
    only under the EXCLUSIVE cluster lock, and everything that runs grants.sql (which revokes from
    those roles when they exist) holds the SHARED one, so a role never vanishes mid-revoke.
The lock is an advisory lock taken in the admin database; a test that holds it must not ask for
it again on another connection (it would wait for itself).
"""
from __future__ import annotations

import contextlib
import os
import pathlib
import shutil
import subprocess
import uuid

import pytest

from _node import running_in_ci

BACKEND = pathlib.Path(__file__).resolve().parents[1]
STAGING_SCHEMA = BACKEND / "staging" / "schema_pg.sql"

CLUSTER_LOCK = 0x0BDC7E57
# The bd_app-like login the tests connect as: a member of bd_app and nothing else, so it holds
# exactly bd_app's rights (the bd_app_all policies apply to bd_app's members too). Test servers
# only; this password guards nothing.
APP_TEST_LOGIN = "bd_test_app"
APP_TEST_PASSWORD = "bd-test-app-only"
SUPABASE_API_ROLES = ("anon", "authenticated", "service_role")


# ── the server ─────────────────────────────────────────────────────────────────────────────────
def is_local_server(url: str) -> bool:
    """True when every host the URL names is this machine (bd.db.is_local_url)."""
    from bd import db as dbmod

    return dbmod.is_local_url(url)


def looks_like_supabase(url: str) -> bool:
    """True when the server is Supabase-shaped: a supabase_admin role, or an auth schema here."""
    with connect(url) as conn:
        return bool(conn.execute(
            "select exists (select 1 from pg_catalog.pg_roles where rolname = 'supabase_admin')"
            " or exists (select 1 from pg_catalog.pg_namespace where nspname = 'auth')").fetchone()[0])


def _refuse(why: str):
    pytest.fail("BD_TEST_DATABASE_URL refused: " + why + ". It must be an admin URL on a throwaway "
                "Postgres 16 on this machine (a local container, or CI's service).", pytrace=False)


def admin_url() -> str:
    """BD_TEST_DATABASE_URL, or skip (locally) / fail (CI) when it is unset. A URL that is not a
    throwaway server on this machine FAILS the run (see test_bd_test_server.py); the message never
    quotes the URL."""
    import psycopg

    url = (os.environ.get("BD_TEST_DATABASE_URL") or "").strip()
    if url:
        if not is_local_server(url):
            _refuse("it does not point at this machine")
        try:
            supabase = looks_like_supabase(url)
        except psycopg.OperationalError:
            supabase = False    # unreachable: new_database() skips (locally) or fails (CI)
        if supabase:
            _refuse("the server looks like Supabase")
        return url
    if running_in_ci():
        pytest.fail("BD_TEST_DATABASE_URL is not set, and CI must have it: the BD database tests would "
                    "otherwise skip and pass a run that tested no database. Fix ci.yml.", pytrace=False)
    pytest.skip("BD_TEST_DATABASE_URL is not set (an admin URL on a throwaway Postgres 16)")


def connect(url: str, **kw):
    import psycopg

    kw.setdefault("autocommit", True)
    kw.setdefault("connect_timeout", 10)
    return psycopg.connect(url, **kw)


def url_for(admin: str, dbname: str, **kw) -> str:
    from psycopg import conninfo

    return conninfo.make_conninfo(admin, dbname=dbname, **kw)


def _new_name() -> str:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
    return "bd_test_%s_%s" % (worker, uuid.uuid4().hex[:10])   # [a-z0-9_] only: safe to splice


@contextlib.contextmanager
def new_database(admin: str, template: str | None = None, options: str = ""):
    """An empty database of its own, dropped afterwards. Yields its (admin) URL. `template` copies
    that database (which must have no open connection); `options` is spliced into CREATE DATABASE
    as written (callers pass fixed SQL, never a value from outside)."""
    import psycopg

    name = _new_name()
    ddl = "create database " + name
    if template is not None:
        if not template.replace("_", "").isalnum():
            raise ValueError("a template database name is [A-Za-z0-9_] only")
        ddl += " template " + template
    if options:
        ddl += " " + options
    try:
        with connect(admin) as conn:
            conn.execute(ddl)
    except psycopg.OperationalError as exc:
        if running_in_ci():
            raise
        pytest.skip("the BD test database server is not reachable: %s" % exc.__class__.__name__)
    try:
        yield url_for(admin, name)
    finally:
        with connect(admin) as conn:
            conn.execute("drop database if exists " + name + " with (force)")


@contextlib.contextmanager
def cluster_lock(admin: str, exclusive: bool):
    """The cross-worker lock on cluster-wide roles (see the module docstring)."""
    with connect(admin) as conn:
        fn = "pg_advisory_lock" if exclusive else "pg_advisory_lock_shared"
        conn.execute("select %s(%%s)" % fn, (CLUSTER_LOCK,))
        try:
            yield
        finally:
            conn.execute("select %s(%%s)" % fn.replace("lock", "unlock", 1), (CLUSTER_LOCK,))


# ── roles ──────────────────────────────────────────────────────────────────────────────────────
def ensure_bd_app(admin: str) -> None:
    """bd_app, made exactly as the staging schema file makes it."""
    from bd.ops import staging_schema

    with connect(admin) as conn:
        conn.execute(staging_schema.BD_APP_ROLE_SQL)


def ensure_app_login(admin: str) -> None:
    ensure_bd_app(admin)
    with connect(admin) as conn:
        conn.execute(
            "do $t$ begin"
            " if not exists (select 1 from pg_roles where rolname = '%s') then"
            "  begin create role %s login password '%s' in role bd_app;"
            "  exception when duplicate_object or unique_violation then null; end;"
            " end if; end $t$" % (APP_TEST_LOGIN, APP_TEST_LOGIN, APP_TEST_PASSWORD))


def app_login_url(db_url: str) -> str:
    """The bd_app-like login on that database, with BD's search_path (the pool sets it again on
    every checkout; a member of bd_app does not inherit bd_app's own role setting)."""
    return url_for(db_url, dbname(db_url), user=APP_TEST_LOGIN, password=APP_TEST_PASSWORD,
                   options="-c search_path=bd,pg_catalog")


def dbname(url: str) -> str:
    from bd import db as dbmod

    return dbmod.dbname(url)


# ── applying the schema ────────────────────────────────────────────────────────────────────────
def migrate(url: str, **kw) -> list:
    from bd import migrate as runner

    return runner.migrate(url, **kw)


def apply_staging_file(url: str, path: pathlib.Path = STAGING_SCHEMA) -> None:
    """Feed the staging schema file to the database the way the staging deploy does: psql with
    ON_ERROR_STOP, statement by statement in autocommit. Without psql on this machine, the whole
    file goes as one simple-protocol query instead (one transaction, the same statements)."""
    psql = shutil.which("psql")
    sql = path.read_text(encoding="utf-8")
    if psql:
        from psycopg import conninfo

        d = conninfo.conninfo_to_dict(url)
        env = dict(os.environ, PGPASSWORD=str(d.get("password") or ""))
        cmd = [psql, "-X", "-q", "-v", "ON_ERROR_STOP=1", "-h", str(d.get("host") or "localhost"),
               "-p", str(d.get("port") or 5432), "-U", str(d.get("user") or "postgres"), "-d", d["dbname"]]
        res = subprocess.run(cmd, input=sql, text=True, encoding="utf-8", capture_output=True, env=env,
                             timeout=120)
        assert res.returncode == 0, "psql failed on the staging schema file:\n" + res.stderr[-4000:]
        return
    with connect(url) as conn:
        conn.execute(sql)


# ── what a database holds, as plain values to compare ──────────────────────────────────────────
def _acl(col: str) -> str:
    return "array(select x::text from unnest(coalesce(%s, '{}'::aclitem[])) x order by 1)" % col


_QUERIES = {
    "schemas": "select nspname, %s from pg_namespace where nspname = any(%%(s)s) order by 1" % _acl("nspacl"),
    "relations": (
        "select n.nspname, c.relname, c.relkind, c.relrowsecurity, c.relforcerowsecurity,"
        " coalesce(c.reloptions, '{}'), %s from pg_class c join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = any(%%(s)s) order by 1, 2" % _acl("c.relacl")),
    "columns": (
        "select n.nspname, c.relname, a.attnum, a.attname, format_type(a.atttypid, a.atttypmod),"
        " a.attnotnull, a.attidentity, a.attgenerated, pg_get_expr(d.adbin, d.adrelid)"
        " from pg_attribute a join pg_class c on c.oid = a.attrelid join pg_namespace n on n.oid = c.relnamespace"
        " left join pg_attrdef d on d.adrelid = a.attrelid and d.adnum = a.attnum"
        " where n.nspname = any(%(s)s) and a.attnum > 0 and not a.attisdropped order by 1, 2, 3"),
    "constraints": (
        "select n.nspname, c.relname, k.conname, pg_get_constraintdef(k.oid) from pg_constraint k"
        " join pg_class c on c.oid = k.conrelid join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = any(%(s)s) order by 1, 2, 3"),
    "indexes": "select schemaname, tablename, indexname, indexdef from pg_indexes"
               " where schemaname = any(%(s)s) order by 1, 2, 3",
    "triggers": (
        "select n.nspname, c.relname, t.tgname, pg_get_triggerdef(t.oid) from pg_trigger t"
        " join pg_class c on c.oid = t.tgrelid join pg_namespace n on n.oid = c.relnamespace"
        " where n.nspname = any(%(s)s) and not t.tgisinternal order by 1, 2, 3"),
    "functions": (
        "select n.nspname, p.oid::regprocedure::text, pg_get_functiondef(p.oid), coalesce(p.proconfig, '{}'), %s"
        " from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
        " where n.nspname = any(%%(s)s) order by 1, 2" % _acl("p.proacl")),
    "views": "select schemaname, viewname, definition from pg_views where schemaname = any(%(s)s) order by 1, 2",
    "policies": (
        "select schemaname, tablename, policyname, permissive, roles::text[], cmd, qual, with_check"
        " from pg_policies where schemaname = any(%(s)s) order by 1, 2, 3"),
    "sequences": (
        "select schemaname, sequencename, data_type::text, start_value, increment_by, last_value"
        " from pg_sequences where schemaname = any(%(s)s) order by 1, 2"),
    "roles": (
        "select rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, rolreplication,"
        " rolbypassrls from pg_roles where rolname = any(%(r)s) order by 1"),
    "role_settings": (
        "select r.rolname, s.setdatabase <> 0, s.setconfig from pg_db_role_setting s"
        " join pg_roles r on r.oid = s.setrole where r.rolname = any(%(r)s) order by 1, 2"),
    "memberships": (
        "select r.rolname, m.rolname from pg_auth_members am join pg_roles r on r.oid = am.roleid"
        " join pg_roles m on m.oid = am.member where m.rolname = any(%(r)s) order by 1, 2"),
}
ROLES_OF_INTEREST = ["bd_app", "service_role", "authenticator", "anon", "authenticated"]


def snapshot(url: str, schemas=("bd",), applied_at: bool = False) -> dict:
    """The catalog state of `schemas` (and of the roles BD and the staging file touch), plus the
    BD ledger and every BD table's row count. applied_at=True also keeps the ledger's timestamps,
    to prove a second run applied nothing."""
    with connect(url) as conn:
        conn.execute("set search_path = pg_catalog")
        params = {"s": list(schemas), "r": ROLES_OF_INTEREST}
        snap = {k: [tuple(r) for r in conn.execute(q, params).fetchall()] for k, q in _QUERIES.items()}
        if conn.execute("select to_regclass('bd.schema_migrations')").fetchone()[0] is not None:
            cols = "name, applied_at" if applied_at else "name"
            snap["ledger"] = [tuple(r) for r in conn.execute(
                "select %s from bd.schema_migrations order by name" % cols).fetchall()]
            tables = [r[0] for r in conn.execute(
                "select c.oid::regclass::text from pg_class c where c.relnamespace = 'bd'::regnamespace"
                " and c.relkind = 'r' order by 1").fetchall()]
            snap["rows"] = [(t, conn.execute("select count(*) from %s" % t).fetchone()[0]) for t in tables]
            snap["settings"] = [tuple(r) for r in conn.execute(
                "select key, value::text from bd.settings order by key").fetchall()] \
                if "bd.settings" in tables else []
    return snap
