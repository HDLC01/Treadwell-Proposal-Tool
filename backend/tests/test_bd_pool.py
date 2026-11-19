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


# ── no database needed ─────────────────────────────────────────────────────────────────────────
def test_nothing_is_created_without_bd_database_url(monkeypatch):
    monkeypatch.setattr(config, "BD_DATABASE_URL", "")
    previous = dbmod.configure(None)
    try:
        assert not dbmod.is_configured()
        with pytest.raises(dbmod.NotConfigured):
            dbmod.get_pool()
        with pytest.raises(dbmod.NotConfigured):
            with dbmod.connect():
                pass
        assert dbmod._pool is None
        assert issubclass(dbmod.NotConfigured, dbmod.Unavailable)
    finally:
        dbmod.configure(previous)


def test_importing_the_module_opens_no_pool():
    import subprocess
    import sys

    code = ("import os; os.environ['BD_DATABASE_URL'] = 'postgresql://u:p@127.0.0.1:1/bd_test_x';"
            "from bd import db; assert db._pool is None; print('ok')")
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


def test_under_pytest_the_pool_refuses_a_database_that_is_not_a_test_one(monkeypatch):
    url = "postgresql://bd_app:%s@127.0.0.1:%d/treadwell" % (SECRET, closed_port())
    with pool_on(url, monkeypatch):
        with pytest.raises(dbmod.RefusedDatabase) as err:
            dbmod.get_pool()
        assert dbmod._pool is None
    assert SECRET not in str(err.value) and "treadwell" not in str(err.value)


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


def test_a_slot_is_reentrant_on_one_thread():
    """A request that holds a slot and then checks out a connection takes ONE slot, not two."""
    with dbmod.request_slot():
        with dbmod.request_slot():
            assert dbmod._slots_in_use() == 1
    assert dbmod._slots_in_use() == 0


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


def test_direct_gives_a_plain_connection_with_the_same_session(bd_db_url, monkeypatch):
    monkeypatch.setenv("BD_TODAY", "2026-11-04")
    conn = dbmod.direct(_bd_db.app_login_url(bd_db_url))
    try:
        row = conn.execute("select current_setting('TimeZone') as tz, current_setting('search_path') as sp,"
                           " bd_today() as d").fetchone()
    finally:
        conn.close()
    assert row == {"tz": "UTC", "sp": "bd, pg_catalog", "d": dt.date(2026, 11, 4)}
