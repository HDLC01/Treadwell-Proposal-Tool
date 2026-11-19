"""The privilege model of schema bd (#805; seam 2 of #802), against a real Postgres 16.

  * public, anon, authenticated and service_role have no rights on schema bd or anything in it,
    even when something (Supabase's defaults, a slip by hand) granted them some: both the runner
    and the staging schema file take those rights away again;
  * contacts_summary is security_invoker; every BD function pins its search_path and none is
    executable by public;
  * every BD table has row level security on with the one bd_app policy, so even a login that was
    granted a table by mistake reads no rows;
  * bd_app holds exactly what the ticket gives it (tables, USAGE/SELECT/UPDATE on sequences,
    execute on functions, select on the ledger and the view), nothing outside schema bd, and its
    search_path on the login;
  * a bd_app-like login inserts a company and a contact (generated columns filled, the
    default-frequency trigger fires) and reads the contacts summary.
"""
from __future__ import annotations

import psycopg
import pytest

import _bd_db
from bd import migrate

STRAY_LOGIN = "bd_test_stray"
STRAY_PASSWORD = "bd-test-stray-only"
TABLE_PRIVS = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")


def _bd_objects(conn):
    rels = conn.execute(
        "select c.oid::regclass::text, c.relkind from pg_class c"
        " where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p', 'v', 'S') order by 1").fetchall()
    funcs = [r[0] for r in conn.execute(
        "select p.oid::regprocedure::text from pg_proc p where p.pronamespace = 'bd'::regnamespace order by 1")]
    return rels, funcs


def _rights(conn, role):
    """Every right `role` holds on schema bd and its objects, through any path (PUBLIC included)."""
    rels, funcs = _bd_objects(conn)
    found = []
    for priv in ("USAGE", "CREATE"):
        if conn.execute("select has_schema_privilege(%s, 'bd', %s)", (role, priv)).fetchone()[0]:
            found.append(("schema bd", priv))
    for name, kind in rels:
        privs = ("USAGE", "SELECT", "UPDATE") if kind == "S" else TABLE_PRIVS
        fn = "has_sequence_privilege" if kind == "S" else "has_table_privilege"
        for priv in privs:
            if conn.execute("select %s(%%s, %%s, %%s)" % fn, (role, name, priv)).fetchone()[0]:
                found.append((name, priv))
    for name in funcs:
        if conn.execute("select has_function_privilege(%s, %s, 'EXECUTE')", (role, name)).fetchone()[0]:
            found.append((name, "EXECUTE"))
    return found


def _mis_grant(url):
    """What Supabase's default privileges (or a slip by hand) could give the API roles."""
    with _bd_db.connect(url) as conn:
        for role in _bd_db.SUPABASE_API_ROLES:
            conn.execute("grant all on schema bd to %s" % role)
            conn.execute("grant all on all tables in schema bd to %s" % role)
            conn.execute("grant all on all sequences in schema bd to %s" % role)
            conn.execute("grant all on all functions in schema bd to %s" % role)
        conn.execute("grant usage on schema bd to public")
        conn.execute("grant select on all tables in schema bd to public")
        conn.execute("grant execute on all functions in schema bd to public")


def _outside_bd(conn):
    """bd_app's rights outside schema bd (direct grants or any table right, through any path)."""
    found = []
    for name, kind in conn.execute(
            "select c.oid::regclass::text, c.relkind from pg_class c join pg_namespace n on n.oid = c.relnamespace"
            " where n.nspname not in ('bd', 'pg_catalog', 'information_schema') and n.nspname !~ '^pg_toast'"
            " and c.relkind in ('r', 'p', 'v', 'm', 'S', 'f')").fetchall():
        if kind == "S":
            fn, privs = "has_sequence_privilege", ("USAGE", "SELECT", "UPDATE")
        else:
            fn, privs = "has_table_privilege", ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
        for priv in privs:
            if conn.execute("select %s('bd_app', %%s, %%s)" % fn, (name, priv)).fetchone()[0]:
                found.append((name, priv))
    for (nsp,) in conn.execute("select nspname from pg_namespace where nspname <> 'bd'").fetchall():
        if conn.execute("select has_schema_privilege('bd_app', %s, 'CREATE')", (nsp,)).fetchone()[0]:
            found.append((nsp, "CREATE"))
    direct = conn.execute(
        "select 'relation ' || c.oid::regclass::text from pg_class c, aclexplode(c.relacl) a"
        " where a.grantee = 'bd_app'::regrole and c.relnamespace <> 'bd'::regnamespace"
        " union all select 'schema ' || n.nspname from pg_namespace n, aclexplode(n.nspacl) a"
        " where a.grantee = 'bd_app'::regrole and n.nspname <> 'bd'"
        " union all select 'function ' || p.oid::regprocedure::text from pg_proc p, aclexplode(p.proacl) a"
        " where a.grantee = 'bd_app'::regrole and p.pronamespace <> 'bd'::regnamespace"
        " union all select 'database ' || d.datname from pg_database d, aclexplode(d.datacl) a"
        " where a.grantee = 'bd_app'::regrole").fetchall()
    found += [(r[0], "direct grant") for r in direct]
    return found


@pytest.fixture(scope="module")
def supabase_like(bd_admin):
    """A database where anon, authenticated and service_role exist and were granted everything on
    schema bd, put right once by the runner and once by the staging schema file. Collects what the
    tests check, then drops the database and the roles it made, all under the exclusive cluster
    lock (see tests/_bd_db.py)."""
    facts = {}
    made = []
    with _bd_db.cluster_lock(bd_admin, exclusive=True):
        with _bd_db.connect(bd_admin) as conn:
            for role in ("anon", "authenticated"):
                if conn.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone() is None:
                    conn.execute("create role %s nologin" % role)
                    made.append(role)
            if conn.execute("select 1 from pg_roles where rolname = %s", (STRAY_LOGIN,)).fetchone() is None:
                conn.execute("create role %s login password '%s'" % (STRAY_LOGIN, STRAY_PASSWORD))
                made.append(STRAY_LOGIN)
        _bd_db.ensure_app_login(bd_admin)
        try:
            with _bd_db.new_database(bd_admin) as url:
                _bd_db.apply_staging_file(url)                 # also makes service_role, as staging has it
                _mis_grant(url)
                migrate.migrate(url)
                with _bd_db.connect(url) as conn:
                    facts["after_runner"] = {r: _rights(conn, r) for r in _bd_db.SUPABASE_API_ROLES}
                    facts["public_after_runner"] = _public_entries(conn)
                _mis_grant(url)
                _bd_db.apply_staging_file(url)
                with _bd_db.connect(url) as conn:
                    facts["after_staging_file"] = {r: _rights(conn, r) for r in _bd_db.SUPABASE_API_ROLES}
                    facts["public_after_staging_file"] = _public_entries(conn)
                    facts["bd_app_outside"] = _outside_bd(conn)
                    # Row level security is a second wall: a login granted a table by mistake reads
                    # nothing, while bd_app's members read the row.
                    conn.execute("insert into bd.companies (name, normalized_name) values ('Wall Co', 'wall co')")
                    conn.execute("grant usage on schema bd to %s" % STRAY_LOGIN)
                    conn.execute("grant select on bd.companies to %s" % STRAY_LOGIN)
                stray = _bd_db.url_for(url, _db_of(url), user=STRAY_LOGIN, password=STRAY_PASSWORD)
                with _bd_db.connect(stray) as conn:
                    facts["stray_rows"] = conn.execute("select count(*) from bd.companies").fetchone()[0]
                with _bd_db.connect(_bd_db.app_login_url(url)) as conn:
                    facts["app_rows"] = conn.execute("select count(*) from bd.companies").fetchone()[0]
        finally:
            with _bd_db.connect(bd_admin) as conn:
                for role in made:
                    conn.execute("drop role if exists %s" % role)
    return facts


def _db_of(url):
    from psycopg import conninfo

    return conninfo.conninfo_to_dict(url)["dbname"]


def _public_entries(conn):
    """ACL entries for PUBLIC (grantee 0) on schema bd and every object in it."""
    return conn.execute(
        "select 'schema bd' from pg_namespace n, aclexplode(n.nspacl) a where n.nspname = 'bd' and a.grantee = 0"
        " union all select c.oid::regclass::text from pg_class c, aclexplode(c.relacl) a"
        " where c.relnamespace = 'bd'::regnamespace and a.grantee = 0"
        " union all select p.oid::regprocedure::text from pg_proc p, aclexplode(p.proacl) a"
        " where p.pronamespace = 'bd'::regnamespace and a.grantee = 0").fetchall()


# ── the API roles and public get nothing ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("role", _bd_db.SUPABASE_API_ROLES)
@pytest.mark.parametrize("path", ["after_runner", "after_staging_file"])
def test_the_api_roles_have_no_rights_on_schema_bd(supabase_like, role, path):
    assert supabase_like[path][role] == []


@pytest.mark.parametrize("path", ["public_after_runner", "public_after_staging_file"])
def test_public_has_no_rights_on_schema_bd(supabase_like, path):
    assert supabase_like[path] == []


def test_row_level_security_lets_only_bd_app_in(supabase_like):
    assert supabase_like["app_rows"] == 1
    assert supabase_like["stray_rows"] == 0


def test_bd_app_has_no_rights_outside_schema_bd(supabase_like):
    assert supabase_like["bd_app_outside"] == []


def test_bd_app_is_a_plain_login_with_its_search_path(bd_migrated_url):
    with _bd_db.connect(bd_migrated_url) as conn:
        attrs = conn.execute(
            "select rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls from pg_roles"
            " where rolname = 'bd_app'").fetchone()
        member_of = conn.execute(
            "select count(*) from pg_auth_members where member = 'bd_app'::regrole").fetchone()[0]
        config = conn.execute(
            "select setconfig from pg_db_role_setting where setrole = 'bd_app'::regrole and setdatabase = 0"
        ).fetchone()
    assert tuple(attrs) == (False, False, False, False, False)
    assert member_of == 0
    assert config is not None and config[0] == ["search_path=bd, pg_catalog"]


# ── the schema's own settings ────────────────────────────────────────────────────────────────────
def test_the_view_is_security_invoker(bd_migrated_url):
    with _bd_db.connect(bd_migrated_url) as conn:
        views = conn.execute(
            "select c.relname, c.reloptions from pg_class c"
            " where c.relnamespace = 'bd'::regnamespace and c.relkind = 'v'").fetchall()
    assert views == [("contacts_summary", ["security_invoker=on"])]


def test_every_function_pins_its_search_path_and_public_cannot_run_it(bd_migrated_url):
    with _bd_db.connect(bd_migrated_url) as conn:
        rows = conn.execute(
            "select p.proname, p.proconfig, p.proacl is null,"
            " exists (select 1 from aclexplode(p.proacl) a where a.grantee = 0)"
            " from pg_proc p where p.pronamespace = 'bd'::regnamespace order by 1").fetchall()
    assert {r[0] for r in rows} == {"bd_today", "bd_now", "bd_date", "bd_e164", "bd_cadence_frequency",
                                    "contacts_default_frequency"}
    for name, config, default_acl, public_runs in rows:
        assert config == ["search_path=bd, pg_catalog"], name
        assert not default_acl, "%s keeps the default ACL, which lets public run it" % name
        assert not public_runs, name


def test_every_table_has_row_level_security_and_the_one_bd_app_policy(bd_migrated_url):
    with _bd_db.connect(bd_migrated_url) as conn:
        tables = conn.execute(
            "select c.relname, c.relrowsecurity from pg_class c"
            " where c.relnamespace = 'bd'::regnamespace and c.relkind in ('r', 'p') order by 1").fetchall()
        policies = conn.execute(
            "select tablename, policyname, permissive, roles::text[], cmd, qual, with_check from pg_policies"
            " where schemaname = 'bd' order by 1, 2").fetchall()
    assert {t for t, _ in tables} >= {"users", "companies", "contacts", "interactions", "schema_migrations"}
    assert [t for t, on in tables if not on] == []
    assert policies == [(t, "bd_app_all", "PERMISSIVE", ["bd_app"], "ALL", "true", "true") for t, _ in tables]


def test_bd_app_holds_exactly_its_rights_in_schema_bd(bd_migrated_url):
    with _bd_db.connect(bd_migrated_url) as conn:
        rels, funcs = _bd_objects(conn)
        held = set(_rights(conn, "bd_app"))
    sequences = [n for n, k in rels if k == "S"]
    assert len(sequences) >= 10, "the identity columns' sequences are missing"
    want = {("schema bd", "USAGE")}
    for name, kind in rels:
        if kind == "S":
            want |= {(name, p) for p in ("USAGE", "SELECT", "UPDATE")}
        elif kind == "v" or name == "bd.schema_migrations":
            want.add((name, "SELECT"))
        else:
            want |= {(name, p) for p in ("SELECT", "INSERT", "UPDATE", "DELETE")}
    want |= {(f, "EXECUTE") for f in funcs}
    assert held == want


# ── a bd_app-like login at work ──────────────────────────────────────────────────────────────────
@pytest.fixture
def app(bd_migrated_url):
    from psycopg.rows import dict_row

    conn = _bd_db.connect(_bd_db.app_login_url(bd_migrated_url), autocommit=False, row_factory=dict_row)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()


def test_the_app_login_inserts_a_company_and_contact_and_reads_the_summary(app):
    assert app.execute("select current_user as u").fetchone()["u"] == _bd_db.APP_TEST_LOGIN
    co = app.execute("insert into companies (name, normalized_name) values ('Northvane Plastics', 'northvane')"
                     " returning id").fetchone()["id"]
    bd_contact = app.execute(
        "insert into contacts (company_id, name, email, phone) values (%s, 'Pat Example', ' Pat@Example.COM ',"
        " '(816) 555-0142') returning id, email_lower, phone_e164, frequency_per_year", (co,)).fetchone()
    assert (bd_contact["email_lower"], bd_contact["phone_e164"], bd_contact["frequency_per_year"]) == (
        "pat@example.com", "+18165550142", 4)
    upkeep = app.execute(
        "insert into contacts (company_id, name, category) values (%s, 'Lee Example', 'maintenance')"
        " returning frequency_per_year", (co,)).fetchone()
    assert upkeep["frequency_per_year"] == 3                             # the trigger fired
    app.execute("insert into interactions (contact_id, kind, outcome, occurred_at) values (%s, 'call', 'answered',"
                " bd_now())", (bd_contact["id"],))
    row = app.execute("select company_name, email_lower, phone_e164, cadence, cadence_status, touches_this_year"
                      " from contacts_summary where id = %s", (bd_contact["id"],)).fetchone()
    assert row == {"company_name": "Northvane Plastics", "email_lower": "pat@example.com",
                   "phone_e164": "+18165550142", "cadence": "quarterly", "cadence_status": "on_track",
                   "touches_this_year": 1}


def test_the_app_login_can_set_a_sequence_past_the_highest_id(app):
    value = app.execute("select setval(pg_get_serial_sequence('bd.contacts', 'id'), 5000) as v").fetchone()["v"]
    assert value == 5000


@pytest.mark.parametrize("sql", [
    "create table bd.extra (n int)",
    "insert into bd.schema_migrations (name) values ('999_x.sql')",
    "delete from bd.schema_migrations",
    "truncate bd.companies",
    "alter table bd.companies add column x int",
    "create function bd.f() returns int language sql as $$ select 1 $$",
])
def test_the_app_login_cannot_change_the_schema_or_the_ledger(app, sql):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        app.execute(sql)
