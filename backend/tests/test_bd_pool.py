"""backend/bd/db.py: BD's connection pool (#805).

What the pool promises, and what these tests pin:
  * lazy: nothing is created until a BD request needs it, and only when BD_DATABASE_URL is set
    (unset: NotConfigured, which the routes answer with 503);
  * psycopg 3 with dict rows, min/max from BD_DB_POOL_MIN / BD_DB_POOL_MAX, a liveness check on
    every checkout (ConnectionPool.check_connection), idle and lifetime limits below the pooler's
    idle timeout, a checkout that waits about 3 seconds at most;
  * at most about 8 BD requests at once (a bulkhead), so a BD outage cannot hold the tool's threads;
  * every checkout sets the session time zone to UTC, the search_path and the Central business
    clock (bd.today / bd.now, read by bd_today() and bd_now());
  * a killed backend is replaced and the next checkout works; a stopped database fails fast;
  * the connection string is never logged or put in an error;
  * under pytest it refuses any connection string that is not a test database (bd_test_*).

The database tests run on the per-worker BD test database as the bd_app-like login (see
tests/_bd_conftest.py). Everything is fictional.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import logging
import socket
import threading
import time

import pytest
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from bd import config
from bd import db as dbmod

import _bd_db

SECRET = "not-a-real-password-0142"


@contextlib.contextmanager
def pool_on(url, monkeypatch, size=(1, 1)):
    """Point BD's pool at `url` with the given min/max for the length of the block, then put back
    whatever it pointed at before (the per-worker test database, usually)."""
    monkeypatch.setattr(config, "BD_DB_POOL_MIN", size[0])
    monkeypatch.setattr(config, "BD_DB_POOL_MAX", size[1])
    previous = dbmod.configure(url)
    try:
        yield
    finally:
        dbmod.configure(previous)


def closed_port() -> int:
    """A localhost port nothing listens on (bound, then released)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def stopped_url(password: str = "x") -> str:
    return "postgresql://bd_test_app:%s@127.0.0.1:%d/bd_test_stopped" % (password, closed_port())


@pytest.fixture
def pools_made(monkeypatch):
    """Every ConnectionPool BD creates while the test runs (none is opened: the spy stands in)."""
    import psycopg_pool

    made = []
    monkeypatch.setattr(psycopg_pool, "ConnectionPool", lambda *a, **kw: made.append(kw))
    return made


# ── no database needed ─────────────────────────────────────────────────────────────────────────
def test_nothing_is_created_without_bd_database_url(monkeypatch, pools_made):
    monkeypatch.setattr(config, "BD_DATABASE_URL", "")
    previous = dbmod.configure(None)
    try:
        assert not dbmod.is_configured()
        with pytest.raises(dbmod.NotConfigured):
            dbmod.get_pool()
        with pytest.raises(dbmod.NotConfigured):
            with dbmod.connect():
                pass
        assert pools_made == []
        assert issubclass(dbmod.NotConfigured, dbmod.Unavailable)
    finally:
        dbmod.configure(previous)


def test_importing_the_module_opens_no_pool():
    import subprocess
    import sys

    code = ("import os, sys; os.environ['BD_DATABASE_URL'] = 'postgresql://u:p@127.0.0.1:1/bd_test_x';"
            "from bd import db; assert db.is_configured();"
            "assert 'psycopg_pool' not in sys.modules and 'psycopg' not in sys.modules; print('ok')")
    res = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=str(_bd_db.BACKEND), timeout=60)
    assert res.returncode == 0 and res.stdout.strip() == "ok", res.stderr


@pytest.mark.parametrize("url, want", [
    ("postgresql://bd_test_app:pw@127.0.0.1:5432/bd_test_gw0_ab12", True),
    ("host=127.0.0.1 dbname=bd_test_main_00ff user=x", True),
    ("postgresql://bd_app:pw@db:5432/treadwell", False),
    ("postgresql://postgres:pw@127.0.0.1:5432/postgres", False),
    ("postgresql://u:pw@aws-0-us-east-1.pooler.supabase.com:5432/postgres", False),
    ("postgresql://u:pw@127.0.0.1:5432/my_bd_test_db", False),
    ("", False),
    ("not a connection string at all ===", False),
])
def test_is_test_database(url, want):
    assert dbmod.is_test_database(url) is want


def test_under_pytest_the_pool_refuses_a_database_that_is_not_a_test_one(monkeypatch, pools_made):
    url = "postgresql://bd_app:%s@127.0.0.1:%d/treadwell" % (SECRET, closed_port())
    with pool_on(url, monkeypatch):
        with pytest.raises(dbmod.RefusedDatabase) as err:
            dbmod.get_pool()
        assert pools_made == []
    assert SECRET not in str(err.value) and "treadwell" not in str(err.value)


@pytest.mark.parametrize("bad", ["password=%s dbname" % SECRET,
                                 "host='127.0.0.1 password=%s" % SECRET,
                                 "postgresql://u:%s@127.0.0.1:5432/bd_test_x?nosuchoption=1" % SECRET])
def test_a_malformed_bd_database_url_is_refused_before_use_and_never_logged(monkeypatch, caplog, pools_made, bad):
    caplog.set_level(logging.DEBUG)
    with pool_on(bad, monkeypatch):
        with pytest.raises(dbmod.NotConfigured) as err:
            with dbmod.connect():
                pass
    assert pools_made == []
    assert SECRET not in str(err.value) and SECRET not in caplog.text
    assert err.value.__cause__ is None and err.value.__context__ is None   # no libpq error rides along


def test_the_pool_settings(monkeypatch):
    monkeypatch.setattr(config, "BD_DB_POOL_MIN", 1)
    monkeypatch.setattr(config, "BD_DB_POOL_MAX", 5)
    opts = dbmod.pool_options("postgresql://u:p@127.0.0.1:1/bd_test_x")
    assert opts["min_size"] == 1 and opts["max_size"] == 5
    assert opts["check"] is ConnectionPool.check_connection
    assert opts["kwargs"]["row_factory"] is dict_row
    assert opts["kwargs"]["autocommit"] is False
    assert opts["open"] is False
    assert 2.0 <= opts["timeout"] <= 3.5
    assert 0 < opts["max_idle"] < dbmod.POOLER_IDLE_TIMEOUT_S
    assert 0 < opts["max_lifetime"] < dbmod.POOLER_IDLE_TIMEOUT_S
    assert opts["max_idle"] <= opts["max_lifetime"]


def test_the_pool_sizes_come_from_the_settings(monkeypatch):
    monkeypatch.setattr(config, "BD_DB_POOL_MIN", 2)
    monkeypatch.setattr(config, "BD_DB_POOL_MAX", 3)
    opts = dbmod.pool_options("postgresql://u:p@127.0.0.1:1/bd_test_x")
    assert (opts["min_size"], opts["max_size"]) == (2, 3)
    monkeypatch.setattr(config, "BD_DB_POOL_MAX", 0)      # a max below the min never wins
    assert dbmod.pool_options("postgresql://u:p@127.0.0.1:1/bd_test_x")["max_size"] == 2


def test_at_most_eight_bd_requests_hold_a_slot_and_the_ninth_is_refused_at_once():
    assert 6 <= dbmod.MAX_CONCURRENT <= 10
    held, release = threading.Barrier(dbmod.MAX_CONCURRENT + 1), threading.Event()

    def hold():
        with dbmod.request_slot():
            held.wait(timeout=10)
            release.wait(timeout=10)

    threads = [threading.Thread(target=hold) for _ in range(dbmod.MAX_CONCURRENT)]
    for t in threads:
        t.start()
    try:
        held.wait(timeout=10)
        started = time.monotonic()
        with pytest.raises(dbmod.Busy):
            with dbmod.request_slot():
                pass
        with pytest.raises(dbmod.Busy):         # a checkout takes a slot too
            with dbmod.connect():
                pass
        assert time.monotonic() - started < 0.5
        assert issubclass(dbmod.Busy, dbmod.Unavailable)
    finally:
        release.set()
        for t in threads:
            t.join(timeout=10)
    with dbmod.request_slot():          # every slot came back
        pass


def test_no_bd_code_is_async():
    """The request slot is per thread and psycopg blocks: a BD route must be a plain `def`, which
    FastAPI runs in its threadpool. An `async def` would share the event loop's one thread with
    every other request (nested slots skipping the bulkhead, the whole tool stalled on a query).

    ONE async def is allowed (#806): web.py's bd_handler, the route class's wrapper. FastAPI's own
    request handler is a coroutine, so the wrapper around it has to be one; it only awaits that
    handler (which runs the plain-def route in the threadpool) and turns an exception into the
    envelope, touching no database. Every BD endpoint itself is checked below."""
    import ast
    import inspect

    from bd import api as bd_api

    allowed = {("web.py", "bd_handler")}
    found = []
    for path in sorted((_bd_db.BACKEND / "bd").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        found += ["%s:%d %s" % (path.name, n.lineno, n.name) for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef) and (path.name, n.name) not in allowed]
    assert found == []
    endpoints = [r.endpoint for r in bd_api.bd_routes()] + [bd_api.bd_not_found]
    assert len(endpoints) > 10
    assert [e.__name__ for e in endpoints if inspect.iscoroutinefunction(e)] == []


def test_a_slot_is_reentrant_on_one_thread():
    """A request that holds a slot and then checks out a connection takes ONE slot, not two: with a
    nested slot held here, every other slot can still be taken on other threads, and only then is
    the next request Busy."""
    others = dbmod.MAX_CONCURRENT - 1
    held, release = threading.Barrier(others + 1), threading.Event()
    refused = []

    def hold():
        with dbmod.request_slot():
            held.wait(timeout=10)
            release.wait(timeout=10)

    def one_more():
        try:
            with dbmod.request_slot():
                pass
        except dbmod.Busy:
            refused.append(True)

    with dbmod.request_slot():
        with dbmod.request_slot():
            threads = [threading.Thread(target=hold) for _ in range(others)]
            for t in threads:
                t.start()
            try:
                held.wait(timeout=10)            # every other slot was free for the taking
                late = threading.Thread(target=one_more)
                late.start()
                late.join(timeout=10)
                assert refused == [True]
            finally:
                release.set()
                for t in threads:
                    t.join(timeout=10)
    # The nested exit gave back exactly one slot: all of them can be held again at once.
    test_at_most_eight_bd_requests_hold_a_slot_and_the_ninth_is_refused_at_once()


# ── on the BD test database ────────────────────────────────────────────────────────────────────
def _pid(conn) -> int:
    return conn.execute("select pg_backend_pid() as pid").fetchone()["pid"]


def test_the_app_pool_runs_as_the_bd_app_like_login_with_dict_rows(bd_db_url):
    with dbmod.connect() as conn:
        row = conn.execute("select current_user as who, current_setting('search_path') as sp").fetchone()
    assert isinstance(row, dict)
    assert row["who"] == _bd_db.APP_TEST_LOGIN
    assert row["sp"] == "bd, pg_catalog"


def test_every_checkout_sets_utc_the_search_path_and_the_business_clock(bd_db_url, monkeypatch):
    app_url = _bd_db.app_login_url(bd_db_url)
    with pool_on(app_url, monkeypatch):
        monkeypatch.setenv("BD_TODAY", "2026-11-04")
        monkeypatch.setenv("BD_NOW", "2026-11-04T15:30:00-06:00")
        with dbmod.connect() as conn:
            first = _pid(conn)
            row = conn.execute(
                "select current_setting('TimeZone') as tz, current_setting('search_path') as sp,"
                " bd_today() as today, bd_now() as now, now() as real_now").fetchone()
            # the session is someone else's next time: leave it in a mess on purpose
            conn.execute("set time zone 'America/Chicago'")
            conn.execute("set search_path = pg_catalog")
        assert row["tz"] == "UTC" and row["sp"] == "bd, pg_catalog"
        assert row["today"] == dt.date(2026, 11, 4)
        assert row["now"] == dt.datetime(2026, 11, 4, 21, 30, tzinfo=dt.UTC)
        assert row["real_now"].utcoffset() == dt.timedelta(0)

        monkeypatch.setenv("BD_TODAY", "2027-01-02")
        monkeypatch.delenv("BD_NOW")
        with dbmod.connect() as conn:
            assert _pid(conn) == first                      # the same physical connection
            row = conn.execute("select current_setting('TimeZone') as tz,"
                               " current_setting('search_path') as sp, bd_today() as today").fetchone()
        assert (row["tz"], row["sp"], row["today"]) == ("UTC", "bd, pg_catalog", dt.date(2027, 1, 2))


def test_the_clock_is_set_again_after_a_rolled_back_checkout(bd_db_url, monkeypatch):
    app_url = _bd_db.app_login_url(bd_db_url)
    with pool_on(app_url, monkeypatch):
        monkeypatch.setenv("BD_TODAY", "2026-03-08")
        with pytest.raises(ZeroDivisionError):
            with dbmod.connect() as conn:
                conn.execute("select 1")
                raise ZeroDivisionError
        with dbmod.connect() as conn:
            assert conn.execute("select bd_today() as d").fetchone()["d"] == dt.date(2026, 3, 8)


def test_a_checkout_is_one_transaction_committed_on_success_rolled_back_on_error(bd_db_url, bd_db):
    with dbmod.connect() as conn:
        conn.execute("insert into companies (name, normalized_name) values ('Pool Commit Test', 'pool commit test')")
    with pytest.raises(RuntimeError):
        with dbmod.connect() as conn:
            conn.execute("insert into companies (name, normalized_name) values ('Pool Rollback Test', 'pool rollback test')")
            raise RuntimeError("boom")
    names = {r["name"] for r in bd_db.execute("select name from companies").fetchall()}
    assert "Pool Commit Test" in names and "Pool Rollback Test" not in names


def test_a_killed_backend_is_replaced_and_the_next_checkout_succeeds(bd_db_url, monkeypatch):
    app_url = _bd_db.app_login_url(bd_db_url)
    with pool_on(app_url, monkeypatch):
        with dbmod.connect() as conn:
            victim = _pid(conn)
        with _bd_db.connect(bd_db_url) as admin:
            assert admin.execute("select pg_terminate_backend(%s)", (victim,)).fetchone()[0] is True
            for _ in range(50):          # wait until the server has really let it go
                if not admin.execute("select 1 from pg_stat_activity where pid = %s", (victim,)).fetchone():
                    break
                time.sleep(0.05)
        with dbmod.connect() as conn:
            row = conn.execute("select pg_backend_pid() as pid, 1 as ok").fetchone()
        assert row["ok"] == 1 and row["pid"] != victim


def test_a_stopped_database_fails_within_about_three_seconds(bd_db_url, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    url = stopped_url(SECRET)
    with pool_on(url, monkeypatch):
        started = time.monotonic()
        with pytest.raises(dbmod.Unavailable) as err:
            with dbmod.connect() as conn:
                conn.execute("select 1")
        elapsed = time.monotonic() - started
    assert elapsed < 4.5, elapsed
    assert SECRET not in str(err.value) and url not in str(err.value)
    assert SECRET not in caplog.text and url not in caplog.text


def test_a_database_that_refuses_the_login_also_fails_fast(bd_db_url, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    from psycopg import conninfo

    url = conninfo.make_conninfo(_bd_db.app_login_url(bd_db_url), password=SECRET)
    with pool_on(url, monkeypatch):
        started = time.monotonic()
        with pytest.raises(dbmod.Unavailable) as err:
            with dbmod.connect():
                pass
        assert time.monotonic() - started < 4.5
    assert SECRET not in str(err.value) and SECRET not in caplog.text


def test_every_checkout_bounds_its_queries_lock_waits_and_idle_transactions(bd_db_url):
    with dbmod.connect() as conn:
        row = conn.execute(
            "select current_setting('statement_timeout') as st, current_setting('lock_timeout') as lt,"
            " current_setting('idle_in_transaction_session_timeout') as it").fetchone()
    for key, limit in (("st", dbmod.STATEMENT_TIMEOUT_MS), ("lt", dbmod.LOCK_TIMEOUT_MS),
                       ("it", dbmod.IDLE_IN_TRANSACTION_TIMEOUT_MS)):
        assert row[key] not in ("0", ""), key                 # 0 means wait forever
        assert row[key] in ("%dms" % limit, "%ds" % (limit // 1000), "%dmin" % (limit // 60000)), (key, row[key])
    assert 0 < dbmod.LOCK_TIMEOUT_MS <= dbmod.STATEMENT_TIMEOUT_MS <= 60_000


def test_a_query_that_runs_too_long_is_unavailable_and_the_slot_comes_back(bd_db_url, monkeypatch):
    monkeypatch.setattr(dbmod, "STATEMENT_TIMEOUT_MS", 200)
    started = time.monotonic()
    with pytest.raises(dbmod.Unavailable):
        with dbmod.connect() as conn:
            conn.execute("select pg_sleep(5)")
    assert time.monotonic() - started < 3
    with dbmod.connect() as conn:                       # the pool and the slot are fine
        assert conn.execute("select 1 as ok").fetchone()["ok"] == 1


def test_a_lock_wait_that_runs_too_long_is_unavailable(bd_db_url, monkeypatch):
    monkeypatch.setattr(dbmod, "LOCK_TIMEOUT_MS", 200)
    with _bd_db.connect(_bd_db.app_login_url(bd_db_url), autocommit=False) as holder:
        holder.execute("select pg_advisory_xact_lock(805)")
        started = time.monotonic()
        with pytest.raises(dbmod.Unavailable):
            with dbmod.connect() as conn:
                conn.execute("select pg_advisory_xact_lock(805)")
        assert time.monotonic() - started < 3
        holder.rollback()


def test_a_connection_lost_mid_request_is_unavailable_and_the_next_checkout_works(bd_db_url):
    with pytest.raises(dbmod.Unavailable) as err:
        with dbmod.connect() as conn:
            conn.execute("select pg_terminate_backend(pg_backend_pid())")
    assert err.value.__suppress_context__
    with dbmod.connect() as conn:
        assert conn.execute("select 1 as ok").fetchone()["ok"] == 1


def test_a_callers_own_database_error_is_not_turned_into_unavailable(bd_db_url):
    import psycopg

    with pytest.raises(psycopg.errors.UndefinedTable):
        with dbmod.connect() as conn:
            conn.execute("select * from no_such_table_805")


def test_direct_gives_a_plain_connection_with_the_same_session(bd_db_url, monkeypatch):
    monkeypatch.setenv("BD_TODAY", "2026-11-04")
    conn = dbmod.direct(_bd_db.app_login_url(bd_db_url))
    try:
        row = conn.execute("select current_setting('TimeZone') as tz, current_setting('search_path') as sp,"
                           " bd_today() as d").fetchone()
    finally:
        conn.close()
    assert row == {"tz": "UTC", "sp": "bd, pg_catalog", "d": dt.date(2026, 11, 4)}
