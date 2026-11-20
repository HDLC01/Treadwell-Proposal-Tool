"""The cut-over copy's preflight, and what it prints (#812).

The forward copy refuses, before it writes anything, and names what is wrong:
  * a schema bd where any table holds rows (each table named). bd.schema_migrations is left out (the
    runner always fills it), and a settings row a migration inserts by itself counts as empty;
  * any other client connected to the old database;
  * a schema bd the runner has not brought up to date;
  * an old database (or schema bd) whose tables and columns are not the ones the command's map
    expects, or whose migrations ledger is not BD's original four;
  * a cut-over record file that already exists (it is never overwritten);
  * a tool-side login that can change schema bd (it must be bd_app).
`check` runs the same preflight and writes nothing.

The command prints names, counts, checksums, account ids and names, and plain error lines: never a
person's name, phone, email, note or any other row data, and never a connection string.
"""
from __future__ import annotations

import pathlib
import re
import shutil
import types

import pytest

import _bd_db
import _bd_old_source as src
from bd.ops import cutover

EXIT_OK, EXIT_ERROR, EXIT_USAGE, EXIT_REFUSED, EXIT_MISMATCH, EXIT_FREEZE = 0, 1, 2, 3, 4, 5


@pytest.fixture(scope="module")
def templates(bd_admin):
    with src.databases(bd_admin) as names:
        yield names


@pytest.fixture
def dbs(bd_admin, templates, tmp_path):
    with src.clone(bd_admin, templates["old"]) as old, src.clone(bd_admin, templates["tool"]) as tool:
        yield types.SimpleNamespace(old=old, tool=tool, app=_bd_db.app_login_url(tool),
                                    record=tmp_path / "cutover-record.json")


def run(dbs, capsys):
    code = cutover.forward(dbs.old, dbs.app, dbs.record)
    return code, capsys.readouterr()


def refused_lines(err):
    return [x for x in err.splitlines() if x.startswith("refusing")]


def bd_counts(url):
    with _bd_db.connect(url) as conn:
        tables = [r[0] for r in conn.execute(
            "select relname from pg_class where relnamespace = 'bd'::regnamespace and relkind = 'r'"
            " and relname <> 'schema_migrations' order by 1").fetchall()]
        return {t: conn.execute("select count(*) from bd.%s" % t).fetchone()[0] for t in tables}


def assert_nothing_written(dbs, filled=()):
    assert {t for t, n in bd_counts(dbs.tool).items() if n} == set(filled)
    assert not dbs.record.exists()


# ── an empty target ─────────────────────────────────────────────────────────────────────────────
def test_a_target_with_rows_is_refused_naming_every_table_that_has_them(dbs, capsys):
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("insert into bd.users (id, email, name, role) values (1, 'a.zz@example.com', 'A Zz', 'admin')")
        conn.execute("insert into bd.companies (id, name, normalized_name) values (1, 'One', 'one'),"
                     " (2, 'Two', 'two')")
        conn.execute("insert into bd.account_pairs_kept (account_a, account_b, decided_by) values (1, 2, 1)")
        conn.execute("insert into bd.settings (key, value) values ('lead_sources', '[]')")
    code, out = run(dbs, capsys)
    assert code == EXIT_REFUSED
    named = sorted(re.match(r"refusing: bd\.(\w+) holds rows", x).group(1)
                   for x in refused_lines(out.err) if "holds rows" in x)
    assert named == ["account_pairs_kept", "companies", "settings", "users"]
    assert_nothing_written(dbs, filled=named)


def test_the_ledger_and_a_migration_inserted_settings_row_count_as_empty(dbs, capsys):
    """Migration 004 inserts settings.bd_cadence by itself (when it finds BD contacts). On a target
    holding only that row and the ledger, the copy runs and the source's settings replace it."""
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("insert into bd.settings (key, value) values ('bd_cadence', '\"quarterly\"')")
        assert conn.execute("select count(*) from bd.schema_migrations").fetchone()[0] == 5
    code, out = run(dbs, capsys)
    assert code == EXIT_OK, out.err
    with _bd_db.connect(dbs.tool) as conn:
        assert conn.execute("select value #>> '{}' from bd.settings where key = 'bd_cadence'").fetchone()[0] \
            == "monthly"
        assert conn.execute("select count(*) from bd.settings").fetchone()[0] == len(src.ROWS["settings"])


def test_the_migration_inserted_settings_keys_are_exactly_what_the_migrations_insert():
    """Every `insert into settings` in schema bd's migrations, read from the files."""
    found = set()
    for path in sorted((_bd_db.BACKEND / "bd" / "migrations").glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"insert\s+into\s+(?:bd\.)?settings\s*\(key,\s*value\)\s*select\s+'(\w+)'", text, re.I):
            found.add(m.group(1))
        assert len(re.findall(r"insert\s+into\s+(?:bd\.)?settings", text, re.I)) == \
            len(re.findall(r"insert\s+into\s+(?:bd\.)?settings\s*\(key,\s*value\)\s*select\s+'\w+'", text, re.I)), path
    assert found == set(cutover.MIGRATION_SETTINGS_KEYS) == {"bd_cadence"}


# ── the old database ────────────────────────────────────────────────────────────────────────────
def test_another_client_on_the_old_database_is_refused(dbs, capsys):
    with _bd_db.connect(dbs.old) as other, _bd_db.connect(dbs.old):
        other.execute("select 1")
        code, out = run(dbs, capsys)
    assert code == EXIT_REFUSED
    assert refused_lines(out.err) == ["refusing: 2 other clients are connected to the old database"]
    assert_nothing_written(dbs)


def test_the_commands_own_session_is_not_another_client(dbs, capsys):
    code, out = run(dbs, capsys)
    assert code == EXIT_OK, out.err


@pytest.mark.parametrize("ddl,table", [
    ("alter table public.contacts add column nickname text", "contacts"),
    ("alter table public.companies alter column city type varchar(80)", "companies"),
    ("alter table public.imports drop column skipped", "imports"),
    ("create table public.newer_things (id bigint primary key)", "newer_things"),
    ("drop table public.unmatched_calls", "unmatched_calls"),
])
def test_an_old_database_that_is_not_the_map_is_refused(dbs, capsys, ddl, table):
    with _bd_db.connect(dbs.old) as conn:
        conn.execute(ddl)
    code, out = run(dbs, capsys)
    assert code == EXIT_REFUSED
    lines = refused_lines(out.err)
    assert lines and all("old database" in x for x in lines)
    assert any(re.search(r"\bpublic\.%s\b" % table, x) for x in lines)
    assert_nothing_written(dbs)


def test_an_old_ledger_that_is_not_bds_four_migrations_is_refused(dbs, capsys):
    with _bd_db.connect(dbs.old) as conn:
        conn.execute("insert into public.schema_migrations (name) values ('005_later.sql')")
    code, out = run(dbs, capsys)
    assert code == EXIT_REFUSED
    assert refused_lines(out.err) == ["refusing: the old database's migrations ledger is not BD's original "
                                      "four (001 to 004): 005_later.sql is unexpected"]
    assert_nothing_written(dbs)


# ── the tool's database ─────────────────────────────────────────────────────────────────────────
def test_a_schema_bd_behind_the_code_is_refused(bd_admin, templates, dbs, tmp_path, capsys):
    older = tmp_path / "older"
    older.mkdir()
    for path in (_bd_db.BACKEND / "bd" / "migrations").glob("*.sql"):
        if not path.name.startswith("005_"):
            shutil.copy(path, older / path.name)
    with _bd_db.new_database(bd_admin) as tool:
        with _bd_db.cluster_lock(bd_admin, exclusive=False):
            _bd_db.migrate(tool, directory=older)
        code = cutover.forward(dbs.old, _bd_db.app_login_url(tool), dbs.record)
        err = capsys.readouterr().err
        assert set(bd_counts(tool).values()) == {0}
    assert code == EXIT_REFUSED
    assert "refusing: schema bd is not migrated up to date (pending: 005_account_merge.sql)" in refused_lines(err)
    assert not dbs.record.exists()


def test_a_schema_bd_that_is_not_the_map_is_refused(dbs, capsys):
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("alter table bd.events add column extra text")
    code, out = run(dbs, capsys)
    assert code == EXIT_REFUSED
    assert any("bd.events" in x and "extra" in x for x in refused_lines(out.err))
    assert_nothing_written(dbs)


def test_an_existing_record_is_never_overwritten(dbs, capsys):
    dbs.record.write_text("{}", encoding="utf-8")
    code, out = run(dbs, capsys)
    assert code == EXIT_REFUSED
    assert any("record" in x and "already exists" in x for x in refused_lines(out.err))
    assert dbs.record.read_text(encoding="utf-8") == "{}"
    assert set(bd_counts(dbs.tool).values()) == {0}


def test_check_runs_the_same_preflight(dbs, capsys):
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("insert into bd.imports (file_name, dry_run) values ('x.csv', true)")
    assert cutover.check(dbs.old, dbs.app) == EXIT_REFUSED
    assert refused_lines(capsys.readouterr().err) == ["refusing: bd.imports holds rows"]


# ── the command line and what it prints ─────────────────────────────────────────────────────────
def test_the_urls_come_from_the_environment_and_are_read_live(monkeypatch):
    from bd import config

    monkeypatch.setenv("BD_CUTOVER_OLD_URL", " postgresql://x@localhost/one ")
    monkeypatch.setenv("BD_CUTOVER_TOOL_URL", "postgresql://y@localhost/two")
    assert (config.cutover_old_url(), config.cutover_tool_url()) == \
        ("postgresql://x@localhost/one", "postgresql://y@localhost/two")
    monkeypatch.delenv("BD_CUTOVER_OLD_URL")
    assert config.cutover_old_url() == ""


@pytest.mark.parametrize("unset", ["BD_CUTOVER_OLD_URL", "BD_CUTOVER_TOOL_URL"])
def test_a_missing_url_is_a_usage_error_naming_the_variable(monkeypatch, capsys, unset, tmp_path):
    monkeypatch.setenv("BD_CUTOVER_OLD_URL", "postgresql://x@localhost/one")
    monkeypatch.setenv("BD_CUTOVER_TOOL_URL", "postgresql://y@localhost/two")
    monkeypatch.delenv(unset)
    assert cutover.main(["forward", "--record", str(tmp_path / "r.json")]) == EXIT_USAGE
    assert unset in capsys.readouterr().err


def test_a_url_on_the_command_line_is_not_accepted(capsys):
    with pytest.raises(SystemExit):
        cutover.main(["forward", "--record", "r.json", "--url", "postgresql://x@localhost/one"])


def test_a_database_that_cannot_be_reached_is_named_without_its_url(dbs, monkeypatch, capsys):
    from psycopg import conninfo

    secret = "not-the-password-zq-7731"
    bad = conninfo.make_conninfo(dbs.old, password=secret, user="bd_no_such_login_zq")
    monkeypatch.setenv("BD_CUTOVER_OLD_URL", bad)
    monkeypatch.setenv("BD_CUTOVER_TOOL_URL", dbs.app)
    assert cutover.main(["forward", "--record", str(dbs.record)]) == EXIT_ERROR
    out = capsys.readouterr()
    text = out.out + out.err
    assert "could not connect to the old database" in text
    for leak in (secret, "bd_no_such_login_zq", _bd_db.dbname(dbs.old), "postgresql://", "password"):
        assert leak not in text
    assert_nothing_written(dbs)


def test_no_subcommand_ever_prints_row_data_or_a_connection_string(dbs, monkeypatch, capsys):
    """Every subcommand and every way it can end, on the fixture's distinctive made-up values: every
    free text a person typed carries "ZQ", and people's names, emails and phones are listed."""
    from psycopg import conninfo

    printed = []

    def main(*args):
        code = cutover.main(list(args))
        out = capsys.readouterr()
        printed.append(out.out + out.err)
        return code

    monkeypatch.setenv("BD_CUTOVER_OLD_URL", dbs.old)
    monkeypatch.setenv("BD_CUTOVER_TOOL_URL", dbs.app)
    assert main("check") == EXIT_OK
    with _bd_db.connect(dbs.old):
        assert main("check") == EXIT_REFUSED                            # another client
    assert main("forward", "--record", str(dbs.record)) == EXIT_OK
    assert main("forward", "--record", str(dbs.record) + ".2") == EXIT_REFUSED     # bd holds rows
    assert main("check") == EXIT_REFUSED
    monkeypatch.setenv("BD_CUTOVER_TOOL_URL", conninfo.make_conninfo(dbs.app, password="wrong-zq-pass"))
    assert main("check") == EXIT_ERROR
    joined = "\n".join(printed)
    assert "Likely duplicate BD accounts" in joined and "users" in joined
    assert "ZQ" not in joined
    for value in src.PERSONAL:
        assert value not in joined, value
    for leak in ("postgresql://", "wrong-zq-pass", _bd_db.APP_TEST_PASSWORD, _bd_db.dbname(dbs.old),
                 _bd_db.dbname(dbs.tool)):
        assert leak not in joined


def test_the_freeze_and_mismatch_endings_print_no_row_data_either(dbs, capsys):
    def someone_writes():
        with _bd_db.connect(dbs.old) as conn:
            conn.execute("update public.contacts set notes = 'Changed ZQ' where id = 51")

    assert cutover.forward(dbs.old, dbs.app, dbs.record, after_source_read=someone_writes) == EXIT_FREEZE
    with _bd_db.connect(dbs.tool) as conn:
        conn.execute("alter table bd.contacts add constraint zz_no_thessaly check (name <> 'Thessaly Brookhart')")
    pathlib.Path(dbs.record).unlink(missing_ok=True)
    code = cutover.forward(dbs.old, dbs.app, dbs.record)
    out = capsys.readouterr()
    assert code == EXIT_ERROR
    assert "bd.contacts" in out.err
    text = out.out + out.err
    assert "ZQ" not in text and "Thessaly" not in text and "zz_no_thessaly" not in text
    assert_nothing_written(dbs)
