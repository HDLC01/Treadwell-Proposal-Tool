"""The BD migrations runner (backend/bd/migrate.py) and BD's schema rules, in schema bd (#805).

Ported from BD's tests/test_migrate.py. What changed in the move: the files and the ledger live in
schema bd; the runner takes the ADMIN url (never bd_app's) and asks for it when none is given; it
re-applies grants.sql after every run; it never runs at app startup; and a read-only
ledger_behind() tells the routes the database is not up to date.
"""
from __future__ import annotations

import ast
import pathlib
import subprocess
import sys
import threading
import time

import psycopg
import pytest

import _bd_db
from bd import migrate

BACKEND = pathlib.Path(__file__).resolve().parents[1]

EXPECTED_TABLES = {"users", "companies", "contacts", "interactions", "task_batches", "tasks",
                   "ai_recommendations", "followup_drafts", "candidates", "integration_events",
                   "unmatched_calls", "settings", "events", "imports", "schema_migrations"}
EXPECTED_FUNCTIONS = {"bd_today", "bd_now", "bd_date", "bd_e164", "bd_cadence_frequency",
                      "contacts_default_frequency"}


@pytest.fixture
def fresh_db(bd_admin):
    """An empty database of its own. bd_app exists, as it does on staging and (by hand) on prod."""
    _bd_db.ensure_bd_app(bd_admin)
    with _bd_db.new_database(bd_admin) as url, _bd_db.cluster_lock(bd_admin, exclusive=False):
        yield url


def _names(schema, url, kind):
    q = {
        "table": "select table_name from information_schema.tables where table_schema = %s"
                 " and table_type = 'BASE TABLE'",
        "view": "select table_name from information_schema.views where table_schema = %s",
        "function": "select p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace"
                    " where n.nspname = %s",
    }[kind]
    with _bd_db.connect(url) as conn:
        return {r[0] for r in conn.execute(q, (schema,))}


# ── the runner ───────────────────────────────────────────────────────────────────────────────────
def test_applies_once_and_is_idempotent(fresh_db):
    names = [p.name for p in migrate.migration_files()]
    assert names[:4] == ["001_schema.sql", "002_import_values_and_event_history.sql",
                         "003_one_friday_batch.sql", "004_cadence_rules.sql"]
    assert migrate.migrate(fresh_db) == names
    once = _bd_db.snapshot(fresh_db, applied_at=True)
    assert migrate.migrate(fresh_db) == []
    assert migrate.migrate(fresh_db) == []
    assert _bd_db.snapshot(fresh_db, applied_at=True) == once           # running again changes nothing
    assert [r[0] for r in once["ledger"]] == names
    assert _names("bd", fresh_db, "table") >= EXPECTED_TABLES
    assert migrate.status(fresh_db) == [(n, True) for n in names]


def test_every_bd_object_lands_in_schema_bd_and_none_in_public(fresh_db):
    before = {k: _names("public", fresh_db, k) for k in ("table", "view", "function")}
    migrate.migrate(fresh_db)
    assert {k: _names("public", fresh_db, k) for k in ("table", "view", "function")} == before
    assert "contacts_summary" in _names("bd", fresh_db, "view")
    assert _names("bd", fresh_db, "function") == EXPECTED_FUNCTIONS
    with _bd_db.connect(fresh_db) as conn:
        # Index, constraint and trigger names belong to tables in bd, so they cannot meet the tool's.
        outside = conn.execute(
            "select count(*) from pg_class c join pg_namespace n on n.oid = c.relnamespace"
            " where n.nspname = 'public'").fetchone()[0]
        assert outside == 0
        cols = [r[0] for r in conn.execute(
            "select column_name from information_schema.columns where table_schema = 'bd'"
            " and table_name = 'contacts_summary' order by ordinal_position")]
    for c in ("id", "company_id", "company_name", "owner_name", "co_owner_name", "duplicate_name",
              "duplicate_company", "last_live_at", "last_attempt_at", "attempts_since_live",
              "touches_this_year", "next_due_date", "cadence_status", "effective_frequency",
              "touches_needed", "cadence_interval_days", "as_of",
              # 004_cadence_rules.sql
              "frequency_per_year", "stored_frequency_per_year", "cadence", "cadence_source",
              "cadence_override", "cadence_override_until", "last_followup_at", "maintenance_due_date",
              "maintenance_due"):
        assert c in cols, c


def test_files_run_in_lexical_order_and_odd_names_are_ignored(fresh_db, tmp_path):
    (tmp_path / "002_second.sql").write_text("insert into log (n) values (2);", encoding="utf-8")
    (tmp_path / "001_first.sql").write_text("create table log (n int); insert into log (n) values (1);", encoding="utf-8")
    (tmp_path / "010_tenth.sql").write_text("insert into log (n) values (10);", encoding="utf-8")
    (tmp_path / "notes.sql").write_text("this is not sql", encoding="utf-8")
    (tmp_path / "3_short.sql").write_text("this is not sql either", encoding="utf-8")
    assert migrate.migrate(fresh_db, tmp_path) == ["001_first.sql", "002_second.sql", "010_tenth.sql"]
    with _bd_db.connect(fresh_db) as conn:
        assert [r[0] for r in conn.execute("select n from log order by n")] == [1, 2, 10]


def test_grants_sql_is_not_a_migration():
    assert migrate.GRANTS_FILE.exists()
    assert migrate.GRANTS_FILE not in migrate.migration_files()


def test_a_failing_file_leaves_nothing_behind_and_runs_again_later(fresh_db, tmp_path):
    (tmp_path / "001_ok.sql").write_text("create table a (n int);", encoding="utf-8")
    (tmp_path / "002_bad.sql").write_text("create table b (n int); select * from no_such_table;", encoding="utf-8")
    with pytest.raises(psycopg.Error):
        migrate.migrate(fresh_db, tmp_path)
    assert "a" in _names("public", fresh_db, "table") and "b" not in _names("public", fresh_db, "table")
    with _bd_db.connect(fresh_db) as conn:
        assert [r[0] for r in conn.execute("select name from bd.schema_migrations")] == ["001_ok.sql"]
        # The lock was given back although the run failed.
        assert conn.execute("select pg_try_advisory_lock(%s)", (migrate.LOCK_KEY,)).fetchone()[0] is True
    (tmp_path / "002_bad.sql").write_text("create table b (n int);", encoding="utf-8")
    assert migrate.migrate(fresh_db, tmp_path) == ["002_bad.sql"]


def test_a_percent_sign_in_a_migration_is_not_a_placeholder(fresh_db, tmp_path):
    (tmp_path / "001_pct.sql").write_text(
        "create table t (s text); insert into t values ('100% sure'); "
        "create function f() returns text language sql as $$ select 'a%s' $$;", encoding="utf-8")
    migrate.migrate(fresh_db, tmp_path)
    with _bd_db.connect(fresh_db) as conn:
        assert conn.execute("select s from t").fetchone()[0] == "100% sure"


def test_a_second_runner_waits_for_the_lock(fresh_db):
    done = []
    with _bd_db.connect(fresh_db) as holder:
        holder.execute("select pg_advisory_lock(%s)", (migrate.LOCK_KEY,))
        t = threading.Thread(target=lambda: done.append(migrate.migrate(fresh_db)), daemon=True)
        t.start()
        time.sleep(0.8)
        assert done == [], "the runner went ahead while another session held the lock"
        holder.execute("select pg_advisory_unlock(%s)", (migrate.LOCK_KEY,))
        t.join(30)
    assert done and done[0] == [p.name for p in migrate.migration_files()]


def test_the_cli_reports_status(fresh_db, capsys):
    assert migrate.main(["--url", fresh_db, "--status"]) == 0
    assert "pending  001_schema.sql" in capsys.readouterr().out
    assert migrate.main(["--url", fresh_db]) == 0
    assert "applied 001_schema.sql" in capsys.readouterr().out
    assert migrate.main(["--url", fresh_db]) == 0
    assert "up to date" in capsys.readouterr().out
    migrate.main(["--url", fresh_db, "--status"])
    assert "applied  001_schema.sql" in capsys.readouterr().out


def test_the_cli_asks_for_the_url_and_never_prints_it(fresh_db, monkeypatch, capsys):
    asked = []
    monkeypatch.setattr(migrate.getpass, "getpass", lambda prompt="": asked.append(prompt) or fresh_db)
    assert migrate.main([]) == 0
    out = capsys.readouterr()
    assert asked, "with no --url the runner must ask for it"
    assert fresh_db not in out.out + out.err
    from psycopg import conninfo
    password = conninfo.conninfo_to_dict(fresh_db).get("password")
    if password:
        assert password not in out.out + out.err


@pytest.mark.parametrize("url", [
    "postgresql://postgres:not-a-real-password-0144@db.example.com:5432/postgres",
    "postgresql://postgres:not-a-real-password-0144@db:5432/treadwell",
    "password=not-a-real-password-0144 dbname",
])
def test_the_cli_takes_url_on_the_command_line_only_for_this_machine(url, capsys):
    """--url puts the admin password in shell history and the process list: fine for a local test
    server, never for staging or prod, where the runner asks for the URL instead."""
    assert migrate.main(["--url", url, "--status"]) == 2
    out = capsys.readouterr()
    assert "not-a-real-password-0144" not in out.out + out.err and "example.com" not in out.err
    assert "--url" in out.err


def test_the_cli_refuses_an_empty_url(monkeypatch):
    monkeypatch.setattr(migrate.getpass, "getpass", lambda prompt="": "  ")
    assert migrate.main([]) == 2


# ── never at app startup ─────────────────────────────────────────────────────────────────────────
def _imports_of(path: pathlib.Path) -> set:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            mod = ("." * node.level) + (node.module or "")
            found |= {mod + "." + a.name for a in node.names} | {mod}
    return found


def test_no_app_module_imports_the_runner():
    """Only the runner itself, BD's ops scripts and the tests may reach it. The app connects as
    bd_app, which cannot change the schema; migrations are run by hand (prod) or by the staging
    schema file (staging)."""
    allowed = {BACKEND / "bd" / "migrate.py"}
    offenders = []
    for path in BACKEND.rglob("*.py"):
        rel = path.relative_to(BACKEND)
        if path in allowed or rel.parts[0] in ("tests", ".venv", "venv") or rel.parts[:2] == ("bd", "ops"):
            continue
        names = _imports_of(path)
        if {"bd.migrate", "..migrate", ".migrate", "bd.migrate.migrate"} & names or any(
                n.startswith("bd.migrate") for n in names) or (
                rel.parts[0] == "bd" and any(n.endswith(".migrate") for n in names)):
            offenders.append(str(rel))
    assert offenders == []


def test_importing_the_app_never_loads_the_runner():
    """In a fresh interpreter, importing the app (which registers every startup hook) never imports
    the runner. The hooks are not RUN here (they start the digest, the refreshers and the sheet
    warm-up); test_no_app_module_imports_the_runner covers what their code imports."""
    code = ("import sys, main\n"
            "assert main.app.router.on_startup, 'no startup hooks found'\n"
            "print('LOADED' if 'bd.migrate' in sys.modules else 'CLEAN')\n")
    res = subprocess.run([sys.executable, "-c", code], cwd=str(BACKEND), capture_output=True, text=True,
                         timeout=300)
    assert res.returncode == 0, res.stderr[-3000:]
    assert res.stdout.strip().splitlines()[-1] == "CLEAN"


# ── ledger_behind: the routes' "database not up to date" check ───────────────────────────────────
def test_ledger_behind_on_an_empty_database_changes_nothing(fresh_db):
    with _bd_db.connect(fresh_db) as conn:
        assert migrate.ledger_behind(conn) is True
        assert conn.execute("select to_regnamespace('bd')").fetchone()[0] is None   # nothing made


def test_ledger_behind_follows_the_code(fresh_db, tmp_path):
    migrate.migrate(fresh_db)
    with _bd_db.connect(fresh_db) as conn:
        assert migrate.ledger_behind(conn) is False
        assert migrate.pending(conn) == []
    for p in migrate.migration_files():
        (tmp_path / p.name).write_bytes(p.read_bytes())
    (tmp_path / "999_next.sql").write_text("select 1;", encoding="utf-8")
    with _bd_db.connect(fresh_db) as conn:
        assert migrate.pending(conn, tmp_path) == ["999_next.sql"]
        assert migrate.ledger_behind(conn, tmp_path) is True
    # A ledger AHEAD of the code (an older image after a rollback) is not behind.
    (tmp_path / "999_next.sql").unlink()
    (tmp_path / "004_cadence_rules.sql").unlink()
    with _bd_db.connect(fresh_db) as conn:
        assert migrate.ledger_behind(conn, tmp_path) is False


def test_bd_app_can_read_the_ledger_with_dict_rows(bd_migrated_url):
    from psycopg.rows import dict_row

    with _bd_db.connect(_bd_db.app_login_url(bd_migrated_url), row_factory=dict_row) as conn:
        assert migrate.ledger_behind(conn) is False


# ── the schema's own rules ───────────────────────────────────────────────────────────────────────
def _company(db, name="Test Co"):
    return db.execute("insert into companies (name, normalized_name) values (%s, %s) returning id",
                      (name, name.lower())).fetchone()["id"]


def test_server_owned_columns_cannot_be_written(bd_owner):
    db = bd_owner
    co = _company(db)
    with pytest.raises(psycopg.errors.GeneratedAlways):
        with db.transaction():
            db.execute("insert into contacts (company_id, name, phone_e164) values (%s, 'A', '+18165550100')", (co,))
    cid = db.execute("insert into contacts (company_id, name, phone, email) values (%s, 'A', '816.555.0100', ' A@Example.COM ')"
                     " returning id", (co,)).fetchone()["id"]
    row = db.execute("select phone_e164, email_lower from contacts where id = %s", (cid,)).fetchone()
    assert row == {"phone_e164": "+18165550100", "email_lower": "a@example.com"}
    with pytest.raises(psycopg.errors.GeneratedAlways):
        with db.transaction():
            db.execute("insert into interactions (contact_id, kind, outcome, occurred_at, counts_as_touch)"
                       " values (%s, 'email', null, now(), true)", (cid,))


@pytest.mark.parametrize("kind,outcome,touch", [
    ("call", "answered", True), ("call", "meeting_set", True), ("call", "no_answer", False),
    ("voicemail", "voicemail", False), ("meeting", None, True), ("hosted", None, True),
    ("email", None, False), ("sms", None, False), ("note", None, False),
])
def test_counts_as_touch_is_the_counting_rule(bd_owner, kind, outcome, touch):
    db = bd_owner
    co = _company(db)
    cid = db.execute("insert into contacts (company_id, name) values (%s, 'A') returning id", (co,)).fetchone()["id"]
    row = db.execute("insert into interactions (contact_id, kind, outcome, occurred_at) values (%s, %s, %s, now())"
                     " returning counts_as_touch", (cid, kind, outcome)).fetchone()
    assert row["counts_as_touch"] is touch


@pytest.mark.parametrize("kind,outcome", [
    ("call", None), ("call", "voicemail"), ("voicemail", "answered"), ("email", "answered"),
    ("meeting", "meeting_set"), ("fax", None),
])
def test_impossible_kind_and_outcome_pairs_are_refused(bd_owner, kind, outcome):
    db = bd_owner
    co = _company(db)
    cid = db.execute("insert into contacts (company_id, name) values (%s, 'A') returning id", (co,)).fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into interactions (contact_id, kind, outcome, occurred_at) values (%s, %s, %s, now())",
                   (cid, kind, outcome))


def test_frequency_defaults_by_category(bd_owner):
    db = bd_owner
    co = _company(db)
    bd = db.execute("insert into contacts (company_id, name) values (%s, 'A') returning frequency_per_year", (co,)).fetchone()
    mt = db.execute("insert into contacts (company_id, name, category) values (%s, 'B', 'maintenance')"
                    " returning frequency_per_year", (co,)).fetchone()
    given = db.execute("insert into contacts (company_id, name, category, frequency_per_year)"
                       " values (%s, 'C', 'maintenance', 6) returning frequency_per_year", (co,)).fetchone()
    assert (bd["frequency_per_year"], mt["frequency_per_year"], given["frequency_per_year"]) == (4, 3, 6)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute("insert into contacts (company_id, name, frequency_per_year) values (%s, 'D', 0)", (co,))


@pytest.mark.parametrize("sql", [
    "insert into users (email, name, role) values ('x@example.com', 'X', 'owner')",
    "insert into users (email, name, role) values ('X@example.com', 'X', 'manager')",
    "insert into contacts (company_id, name, category) values ({co}, 'A', 'retail')",
    "insert into contacts (company_id, name, source) values ({co}, 'A', 'website')",
    "insert into contacts (company_id, name, importance) values ({co}, 'A', 4)",
    "insert into task_batches (owner_id, week_start, kind) values ({u}, '2026-11-04', 'friday')",
    "insert into task_batches (owner_id, week_start, kind) values ({u}, '2026-11-02', 'monthly')",
])
def test_check_constraints_refuse_bad_enums(bd_owner, sql):
    db = bd_owner
    co = _company(db)
    u = db.execute("insert into users (email, name, role) values ('t@example.com', 'T', 'salesperson') returning id").fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(sql.format(co=co, u=u))


def test_provider_and_external_id_are_unique_but_nulls_are_not(bd_owner):
    db = bd_owner
    co = _company(db)
    cid = db.execute("insert into contacts (company_id, name) values (%s, 'A') returning id", (co,)).fetchone()["id"]
    for _ in range(2):
        db.execute("insert into interactions (contact_id, kind, occurred_at, provider) values (%s, 'note', now(), 'manual')", (cid,))
    db.execute("insert into interactions (contact_id, kind, outcome, occurred_at, provider, external_id)"
               " values (%s, 'call', 'answered', now(), 'quo', 'AC1')", (cid,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute("insert into interactions (contact_id, kind, outcome, occurred_at, provider, external_id)"
                   " values (%s, 'call', 'answered', now(), 'quo', 'AC1')", (cid,))


def test_defaults_use_the_business_clock(bd_owner):
    from bd import bizdate

    bd_owner.execute("set local bd.today = '2026-11-04'")
    bd_owner.execute("set local bd.now = '2026-11-04T18:00:00Z'")
    row = bd_owner.execute("insert into companies (name, normalized_name) values ('Clock Co', 'clock')"
                           " returning created_at, bd_today() as today").fetchone()
    assert bizdate.biz_date(row["created_at"]).isoformat() == "2026-11-04"
    assert row["today"].isoformat() == "2026-11-04"


# ── 004_cadence_rules.sql ────────────────────────────────────────────────────────────────────────
def _004():
    return next(p for p in migrate.migration_files() if p.name == "004_cadence_rules.sql")


def _snapshot(conn):
    """Everything 004 touches, as plain values to compare."""
    return {
        "view": conn.execute("select pg_get_viewdef('bd.contacts_summary'::regclass) as d").fetchone()["d"],
        "options": conn.execute("select reloptions from pg_class where oid = 'bd.contacts_summary'::regclass"
                                ).fetchone()["reloptions"],
        "rows": conn.execute("select * from contacts_summary order by id").fetchall(),
        "settings": conn.execute("select key, value from settings order by key").fetchall(),
        "checks": conn.execute(
            "select conrelid::regclass::text as t, conname, pg_get_constraintdef(oid) as d from pg_constraint"
            " where contype = 'c' and conrelid in ('bd.contacts'::regclass, 'bd.tasks'::regclass) order by 1, 2").fetchall(),
        "columns": conn.execute(
            "select column_name, data_type from information_schema.columns where table_schema = 'bd'"
            " and table_name = 'contacts' order by ordinal_position").fetchall(),
        "function": conn.execute(
            "select pg_get_functiondef('bd.bd_cadence_frequency(text)'::regprocedure) as d").fetchone()["d"],
    }


def test_migration_004_is_idempotent(bd_owner):
    db = bd_owner
    co = _company(db)
    for n, f in enumerate([12, 12, 4]):
        db.execute("insert into contacts (company_id, name, frequency_per_year) values (%s, %s, %s)", (co, "P%d" % n, f))
    db.execute("""insert into settings (key, value) values ('bd_cadence', '"monthly"'),"""
               """ ('default_frequency', '{"maintenance": 3}')""")
    sql = migrate.read_sql(_004())
    once = _snapshot(db)
    assert once["options"] == ["security_invoker=on"]
    assert any(c["conname"] == "tasks_kind_check" and "maintenance" in c["d"] for c in once["checks"])
    assert any(c["conname"] == "contacts_cadence_override_check" for c in once["checks"])
    assert {"cadence_override", "cadence_override_until"} <= {c["column_name"] for c in once["columns"]}
    assert {r["key"] for r in once["settings"]} >= {"bd_cadence", "default_frequency"}
    db.execute(sql)
    twice = _snapshot(db)
    assert twice == once
    db.execute(sql)
    assert _snapshot(db) == once


@pytest.fixture
def old_db(fresh_db, tmp_path):
    """A database at migration 003 (the shape before the cadence rules), and a folder holding 004."""
    older = tmp_path / "old"
    older.mkdir()
    for p in migrate.migration_files():
        if p.name < "004":
            (older / p.name).write_bytes(p.read_bytes())
    assert migrate.migrate(fresh_db, older) == ["001_schema.sql", "002_import_values_and_event_history.sql",
                                                "003_one_friday_batch.sql"]
    newer = tmp_path / "new"
    newer.mkdir()
    (newer / "004_cadence_rules.sql").write_bytes(_004().read_bytes())
    return fresh_db, newer


def _add_old_contacts(url, freqs, category="bd"):
    with _bd_db.connect(url) as conn:
        conn.execute("insert into bd.companies (name, normalized_name) values ('Old Co', 'old co')"
                     " on conflict do nothing")
        co = conn.execute("select id from bd.companies where name = 'Old Co'").fetchone()[0]
        for n, f in enumerate(freqs):
            conn.execute("insert into bd.contacts (company_id, name, category, frequency_per_year)"
                         " values (%s, %s, %s, %s)", (co, "Old %d" % n, category, f))


def _settings(url):
    with _bd_db.connect(url) as conn:
        return dict(conn.execute("select key, value from bd.settings"))


@pytest.mark.parametrize("freqs,word", [
    ([12, 12, 4], "monthly"), ([52, 52, 12, 4], "weekly"), ([4, 4, 12], "quarterly"),
    ([6, 6, 6], "quarterly"), ([2], "quarterly"), ([52], "weekly"),
])
def test_migration_004_takes_the_bd_cadence_from_what_the_data_does(old_db, freqs, word):
    url, newer = old_db
    _add_old_contacts(url, freqs)
    with _bd_db.connect(url) as conn:
        conn.execute("""insert into bd.settings (key, value) values ('default_frequency', '{"bd": 4, "maintenance": 2}')""")
    assert migrate.migrate(url, newer) == ["004_cadence_rules.sql"]
    s = _settings(url)
    assert s["bd_cadence"] == word
    assert s["default_frequency"] == {"maintenance": 2}                # bd stripped, maintenance kept
    assert migrate.migrate(url, newer) == []


def test_migration_004_leaves_an_empty_database_on_the_default(old_db):
    url, newer = old_db
    migrate.migrate(url, newer)
    assert "bd_cadence" not in _settings(url)                          # no BD contacts: the default applies


def test_migration_004_never_rewrites_a_cadence_that_is_set(old_db):
    url, newer = old_db
    _add_old_contacts(url, [52, 52])
    with _bd_db.connect(url) as conn:
        conn.execute("""insert into bd.settings (key, value) values ('bd_cadence', '"quarterly"')""")
    migrate.migrate(url, newer)
    assert _settings(url)["bd_cadence"] == "quarterly"


def test_migration_004_counts_only_bd_contacts_for_the_mode(old_db):
    url, newer = old_db
    _add_old_contacts(url, [3, 3, 3, 3, 3], category="maintenance")
    _add_old_contacts(url, [12])
    migrate.migrate(url, newer)
    assert _settings(url)["bd_cadence"] == "monthly"


def test_migration_004_keeps_existing_rows_and_allows_the_new_task_kind(old_db):
    url, newer = old_db
    _add_old_contacts(url, [4])
    with _bd_db.connect(url) as conn:
        u = conn.execute("insert into bd.users (email, name, role) values ('t@example.com', 'T', 'salesperson')"
                         " returning id").fetchone()[0]
        b = conn.execute("insert into bd.task_batches (owner_id, week_start, kind) values (%s, '2026-11-02', 'friday')"
                         " returning id", (u,)).fetchone()[0]
        c = conn.execute("select id from bd.contacts").fetchone()[0]
        conn.execute("insert into bd.tasks (batch_id, contact_id, kind) values (%s, %s, 'new')", (b, c))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("insert into bd.tasks (batch_id, contact_id, kind) values (%s, %s, 'maintenance')", (b, c))
    migrate.migrate(url, newer)
    with _bd_db.connect(url) as conn:
        assert conn.execute("select count(*) from bd.tasks where kind = 'new'").fetchone()[0] == 1
        conn.execute("update bd.tasks set kind = 'maintenance'")
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("update bd.tasks set kind = 'weekly'")
        row = conn.execute("select cadence, cadence_source, frequency_per_year, maintenance_due"
                           " from bd.contacts_summary").fetchone()
    assert row == ("quarterly", "global", 4, False)
