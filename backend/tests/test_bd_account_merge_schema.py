"""Migration 005 (#811): the merge mark on companies and the kept-pairs table.

    companies.merged_into / merged_at / merged_by   the soft merge's mark (null on every live account)
    account_pairs_kept (account_a < account_b, decided_by, decided_at)   one row per Keep separate

The migration is ADDITIVE ONLY: nullable columns, one new table, a check and indexes. It must apply
to a database that already holds live rows and keep every one of them, and bd_app must be able to
use what it adds through grants.sql alone (which walks the catalog, so it names nothing new).
Everything here is made up: example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import json
import re

import psycopg
import pytest

import _bd_db
from bd import migrate
from bd.ops import fixture_seed

NAME = "005_account_merge.sql"


def _005():
    return next(p for p in migrate.migration_files() if p.name == NAME)


def test_005_is_the_next_numbered_file():
    names = [p.name for p in migrate.migration_files()]
    assert names[:5] == ["001_schema.sql", "002_import_values_and_event_history.sql",
                         "003_one_friday_batch.sql", "004_cadence_rules.sql", NAME]


def test_005_only_adds():
    """No DROP, no DELETE, no UPDATE, no TRUNCATE, no data backfill: only new columns, a new table,
    a check and indexes. Comments are left out of the look."""
    sql = re.sub(r"--[^\n]*", "", migrate.read_sql(_005())).lower()
    for word in ("drop", "delete", "update", "truncate", "insert", "rename", "alter column"):
        assert word not in sql, word
    statements = [" ".join(s.split()) for s in sql.split(";") if s.strip()]
    for s in statements:
        assert s.startswith(("set local search_path", "alter table companies add", "create table account_pairs_kept",
                             "create index", "comment on")), s
        if s.startswith("alter table companies"):
            assert "not null" not in s.replace("is not null", ""), s     # live rows: new columns are nullable


# ── on a database that already holds rows ───────────────────────────────────────────────────────
@pytest.fixture
def at_004(bd_admin, tmp_path):
    """A database at migration 004 holding the fixture seed, and a folder holding 001-005."""
    _bd_db.ensure_app_login(bd_admin)
    older = tmp_path / "old"
    older.mkdir()
    for p in migrate.migration_files():
        if p.name < "005":
            (older / p.name).write_bytes(p.read_bytes())
    with _bd_db.new_database(bd_admin) as url, _bd_db.cluster_lock(bd_admin, exclusive=False):
        assert migrate.migrate(url, older)[-1] == "004_cadence_rules.sql"
        with _bd_db.connect(_bd_db.app_login_url(url)) as conn:
            fixture_seed.seed(conn)
        yield url


def _rows(url):
    """Every BD table's rows as JSON text, by id (or by every column when there is no id)."""
    with _bd_db.connect(url) as conn:
        tables = [r[0] for r in conn.execute(
            "select c.relname from pg_class c where c.relnamespace = 'bd'::regnamespace and c.relkind = 'r'"
            " order by 1")]
        out = {}
        for t in tables:
            out[t] = [r[0] for r in conn.execute(
                "select row_to_json(x)::text from bd.%s x order by row_to_json(x)::text" % t)]
    return out


def _without_mark(table, row_json):
    row = json.loads(row_json)
    if table == "companies":
        for col in ("merged_into", "merged_at", "merged_by"):
            assert row.pop(col) is None, (col, row)
    return row


def test_005_on_a_database_holding_rows_keeps_every_row(at_004):
    before = _rows(at_004)
    assert before["companies"] and before["contacts"] and before["interactions"] and before["tasks"]
    assert "account_pairs_kept" not in before
    assert migrate.migrate(at_004) == [NAME]
    after = _rows(at_004)
    assert after.pop("account_pairs_kept") == []
    assert set(after) == set(before)
    ledger_before, ledger_after = before.pop("schema_migrations"), after.pop("schema_migrations")
    assert ledger_after[:-1] == ledger_before and NAME in ledger_after[-1]
    for table in before:
        assert [_without_mark(table, r) for r in after[table]] == [json.loads(r) for r in before[table]], table
    assert migrate.migrate(at_004) == []                         # applying again changes nothing
    assert _rows(at_004) == dict(after, account_pairs_kept=[], schema_migrations=ledger_after)
    with _bd_db.connect(at_004) as conn:
        assert [r[0] for r in conn.execute("select name from bd.schema_migrations order by name")][-1] == NAME


# ── the rules the schema itself keeps ───────────────────────────────────────────────────────────
def _two_companies(db):
    return [db.execute("insert into companies (name, normalized_name) values (%s, %s) returning id",
                       (n, n.lower())).fetchone()["id"] for n in ("Made Up Alpha", "Made Up Beta")]


def _user(db):
    return db.execute("insert into users (email, name, role) values ('kept.test@example.com', 'Kept Test',"
                      " 'assistant') returning id").fetchone()["id"]


@pytest.mark.parametrize("pair", ["ba", "aa"])
def test_a_kept_pair_is_stored_low_id_first(bd_owner, pair):
    a, b = _two_companies(bd_owner)
    u = _user(bd_owner)
    ids = {"a": a, "b": b}
    with pytest.raises(psycopg.errors.CheckViolation):
        bd_owner.execute("insert into account_pairs_kept (account_a, account_b, decided_by) values (%s, %s, %s)",
                         (ids[pair[0]], ids[pair[1]], u))


def test_a_kept_pair_is_stored_once(bd_owner):
    a, b = _two_companies(bd_owner)
    u = _user(bd_owner)
    row = bd_owner.execute("insert into account_pairs_kept (account_a, account_b, decided_by) values (%s, %s, %s)"
                           " returning decided_at", (a, b, u)).fetchone()
    assert row["decided_at"] is not None
    with pytest.raises(psycopg.errors.UniqueViolation):
        bd_owner.execute("insert into account_pairs_kept (account_a, account_b, decided_by) values (%s, %s, %s)",
                         (a, b, u))


def test_a_kept_pair_names_real_accounts_and_a_real_person(bd_owner):
    a, b = _two_companies(bd_owner)
    u = _user(bd_owner)
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        with bd_owner.transaction():
            bd_owner.execute("insert into account_pairs_kept (account_a, account_b, decided_by)"
                             " values (%s, 999999, %s)", (a, u))
    with pytest.raises(psycopg.errors.NotNullViolation):
        bd_owner.execute("insert into account_pairs_kept (account_a, account_b) values (%s, %s)", (a, b))


def test_an_account_cannot_be_merged_into_itself_or_nowhere(bd_owner):
    a, b = _two_companies(bd_owner)
    u = _user(bd_owner)
    bd_owner.execute("update companies set merged_into = %s, merged_at = bd_now(), merged_by = %s where id = %s",
                     (b, u, a))
    for sql, args, error in (
            ("update companies set merged_into = id, merged_at = bd_now() where id = %s", (b,),
             psycopg.errors.CheckViolation),
            ("update companies set merged_into = %s, merged_at = null where id = %s", (a, b),
             psycopg.errors.CheckViolation),
            ("update companies set merged_into = 999999, merged_at = bd_now() where id = %s", (b,),
             psycopg.errors.ForeignKeyViolation)):
        with pytest.raises(error):
            with bd_owner.transaction():
                bd_owner.execute(sql, args)


def test_bd_app_uses_the_new_objects_through_grants_sql_alone(bd_migrated_url):
    with _bd_db.connect(_bd_db.app_login_url(bd_migrated_url), autocommit=False) as conn:
        a, b = [conn.execute("insert into companies (name, normalized_name) values (%s, %s) returning id",
                             (n, n.lower())).fetchone()[0] for n in ("Grant Alpha", "Grant Beta")]
        u = conn.execute("insert into users (email, name, role) values ('grant.test@example.com', 'Grant Test',"
                         " 'assistant') returning id").fetchone()[0]
        conn.execute("insert into account_pairs_kept (account_a, account_b, decided_by) values (%s, %s, %s)", (a, b, u))
        assert conn.execute("select count(*) from account_pairs_kept").fetchone()[0] == 1
        conn.execute("update companies set merged_into = %s, merged_at = bd_now(), merged_by = %s where id = %s",
                     (b, u, a))
        conn.execute("update companies set merged_into = null, merged_at = null, merged_by = null where id = %s", (a,))
        conn.execute("delete from account_pairs_kept")
        conn.rollback()
    with _bd_db.connect(bd_migrated_url) as conn:
        rls, policies = conn.execute(
            "select c.relrowsecurity, (select array_agg(polname::text) from pg_policy where polrelid = c.oid)"
            " from pg_class c where c.oid = 'bd.account_pairs_kept'::regclass").fetchone()
        assert rls is True and policies == ["bd_app_all"]
        public = conn.execute("select has_table_privilege('public', 'bd.account_pairs_kept', 'select')").fetchone()[0]
        assert public is False
