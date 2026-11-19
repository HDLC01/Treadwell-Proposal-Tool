"""The BD part of backend/staging/schema_pg.sql (#805, seam 2 of #802).

The staging deploy only feeds that file to Postgres (deploy/remote-deploy.sh, a root-owned copy on
the server), so BD's schema reaches staging with no server change by being IN the file: a part
generated from backend/bd/migrations/ by backend/bd/ops/staging_schema.py. These tests prove the
committed part is exactly the generator's output, that the file applies twice to a bare Postgres
16 with no Supabase roles and the second run changes nothing, and that it gives the same schema
as the runner.

Regenerate after changing a migration or grants.sql (from backend/):
    python -m bd.ops.staging_schema
"""
from __future__ import annotations

import pathlib

import pytest

import _bd_db
from bd import migrate
from bd.ops import staging_schema

BACKEND = pathlib.Path(__file__).resolve().parents[1]


def _committed() -> str:
    return _bd_db.STAGING_SCHEMA.read_text(encoding="utf-8")


# ── the committed part is the generated part ─────────────────────────────────────────────────────
def test_the_committed_bd_part_is_the_generators_output():
    assert staging_schema.current_section(_committed()) == staging_schema.render_section(), (
        "backend/staging/schema_pg.sql's BD part is stale: run `python -m bd.ops.staging_schema` "
        "from backend/ and commit the result")


def test_the_bd_part_appears_once_and_the_tool_part_is_untouched():
    text = _committed().replace("\r\n", "\n")
    assert text.count(staging_schema.BEGIN_MARK) == 1 and text.count(staging_schema.END_MARK) == 1
    before, _, rest = text.partition(staging_schema.BEGIN_MARK)
    _, _, after = rest.partition(staging_schema.END_MARK)
    assert "create table if not exists public.drafts" in before        # the tool's part is still there
    assert after.strip() == ""                                         # the BD part is the file's end
    assert " bd." not in before and "schema bd" not in before          # nothing of BD's outside it


def test_check_passes_on_the_committed_file_and_fails_on_a_stale_one(tmp_path, capsys):
    path = tmp_path / "schema_pg.sql"
    path.write_bytes(_bd_db.STAGING_SCHEMA.read_bytes())
    assert staging_schema.main(["--check", "--file", str(path)]) == 0
    path.write_bytes(path.read_bytes().replace(b"001_schema.sql'", b"001_schemaX.sql'", 1))
    assert staging_schema.main(["--check", "--file", str(path)]) == 1
    assert "stale" in capsys.readouterr().err


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_writing_keeps_the_files_line_endings_and_its_tool_part(tmp_path, newline):
    tool_part = "-- the tool's part\ncreate table if not exists public.t (n int);\n".replace("\n", newline)
    path = tmp_path / "schema_pg.sql"
    path.write_bytes(tool_part.encode("utf-8"))
    assert staging_schema.main(["--file", str(path)]) == 0
    once = path.read_bytes().decode("utf-8")
    assert once.startswith(tool_part)
    if newline == "\r\n":
        assert "\n" not in once.replace("\r\n", "")                     # no bare LF slipped in
    else:
        assert "\r" not in once
    assert staging_schema.main(["--file", str(path)]) == 0
    assert path.read_bytes().decode("utf-8") == once                     # writing again changes nothing
    assert staging_schema.main(["--check", "--file", str(path)]) == 0


def test_each_numbered_file_is_applied_only_when_the_ledger_lacks_it():
    section = staging_schema.render_section()
    files = migrate.migration_files()
    assert [p.name for p in files][:4] == ["001_schema.sql", "002_import_values_and_event_history.sql",
                                           "003_one_friday_batch.sql", "004_cadence_rules.sql"]
    at = -1
    for p in files:
        guard = "if not exists (select 1 from bd.schema_migrations where name = '%s')" % p.name
        record = "insert into bd.schema_migrations (name) values ('%s');" % p.name
        body = migrate.read_sql(p)
        assert section.count(guard) == 1 and section.count(record) == 1, p.name
        assert body in section, "%s is not embedded verbatim" % p.name
        here = section.index(guard)
        assert here > at, "the files must apply in the runner's order"
        at = here
    lock = section.index("pg_advisory_lock(%d)" % migrate.LOCK_KEY)
    assert lock < section.index(migrate.BOOTSTRAP_SQL) < section.index(files[0].name)
    assert section.index(migrate.grants_sql()) > at                     # grants after every file
    assert section.rindex("pg_advisory_unlock(%d)" % migrate.LOCK_KEY) > section.index(migrate.grants_sql())


def test_bd_app_is_made_with_a_staging_only_password():
    section = staging_schema.render_section()
    assert staging_schema.BD_APP_ROLE_SQL in section
    assert section.index(staging_schema.BD_APP_ROLE_SQL) < section.index(migrate.grants_sql())
    assert "STAGING-ONLY" in section
    pw = staging_schema.STAGING_ONLY_BD_APP_PASSWORD
    assert "'%s'" % pw in staging_schema.BD_APP_ROLE_SQL
    # Never reused: not in prod's schema, prod's compose file or the env template.
    for rel in ("backend/supabase_schema.sql", "docker-compose.yml", "backend/.env.example"):
        path = BACKEND.parent / rel
        if path.exists():
            assert pw not in path.read_text(encoding="utf-8"), rel


# ── against a real Postgres 16 ───────────────────────────────────────────────────────────────────
def _no_supabase_roles(admin):
    with _bd_db.connect(admin) as conn:
        found = [r[0] for r in conn.execute(
            "select rolname from pg_roles where rolname in ('anon', 'authenticated')").fetchall()]
    assert not found, ("the test server holds %s, so it is not bare; another test failed to drop them"
                       % ", ".join(found))


def test_the_staging_file_applies_twice_to_a_bare_postgres_and_the_second_run_changes_nothing(bd_admin):
    with _bd_db.cluster_lock(bd_admin, exclusive=True):
        _no_supabase_roles(bd_admin)
        with _bd_db.new_database(bd_admin) as url:
            _bd_db.apply_staging_file(url)
            first = _bd_db.snapshot(url, schemas=("bd", "public"), applied_at=True)
            _bd_db.apply_staging_file(url)
            second = _bd_db.snapshot(url, schemas=("bd", "public"), applied_at=True)
    assert [r[0] for r in first["ledger"]] == [p.name for p in migrate.migration_files()]
    assert first["relations"], "nothing was created"
    assert second == first


def test_the_staging_file_gives_the_same_schema_as_the_runner(bd_admin):
    with _bd_db.cluster_lock(bd_admin, exclusive=True):
        _bd_db.ensure_bd_app(bd_admin)
        with _bd_db.new_database(bd_admin) as by_runner, _bd_db.new_database(bd_admin) as by_file:
            assert migrate.migrate(by_runner) == [p.name for p in migrate.migration_files()]
            _bd_db.apply_staging_file(by_file)
            runner_schema = _bd_db.snapshot(by_runner)
            file_schema = _bd_db.snapshot(by_file)
    for key in runner_schema:
        assert file_schema[key] == runner_schema[key], key


def test_the_runner_and_the_staging_file_keep_one_ledger(bd_admin):
    with _bd_db.cluster_lock(bd_admin, exclusive=True):
        _bd_db.ensure_bd_app(bd_admin)
        with _bd_db.new_database(bd_admin) as url:
            migrate.migrate(url)
            before = _bd_db.snapshot(url, applied_at=True)
            _bd_db.apply_staging_file(url)                    # a deploy after a hand run
            assert _bd_db.snapshot(url, applied_at=True) == before
        with _bd_db.new_database(bd_admin) as url:
            _bd_db.apply_staging_file(url)
            assert migrate.migrate(url) == []                  # a hand run after a deploy
            with _bd_db.connect(url) as conn:
                assert migrate.ledger_behind(conn) is False
