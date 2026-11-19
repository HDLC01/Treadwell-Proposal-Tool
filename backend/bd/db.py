"""BD's database: one psycopg 3 connection pool, plain SQL, dict rows.

    from bd import db
    with db.connect() as conn:                     # a pooled connection, ONE transaction
        row = conn.execute("select * from contacts_summary where id = %s", (cid,)).fetchone()
        conn.execute("update contacts set notes = %s where id = %s", (notes, cid))
    # leaving the block commits; an exception rolls back and re-raises

Rules for every caller:
  * Values ALWAYS go in as parameters (%s / %(name)s). Never format a value into SQL text.
  * Rows are dicts (psycopg.rows.dict_row). Timestamps come back as aware UTC datetimes (the
    session time zone is UTC); render them with serialize / bizdate.to_iso_central.
  * Unavailable (and its kinds NotConfigured and Busy) means "BD's database cannot serve this
    request now": the routes answer 503. It never carries the connection string.

THE POOL (#805):
  * Created LAZILY, on the first checkout, and only when BD_DATABASE_URL is set. Unset, every
    checkout raises NotConfigured and nothing is opened. Importing this module opens nothing.
  * min/max from BD_DB_POOL_MIN / BD_DB_POOL_MAX (1 / 5). Prod reaches Supabase through the
    SESSION pooler (the transaction pooler would break session settings and advisory locks).
  * A liveness check on every checkout (ConnectionPool.check_connection), so a connection the
    server killed (a restart, an idle cut) is thrown away and replaced, not handed to a request.
  * Idle and lifetime limits (MAX_IDLE_S, MAX_LIFETIME_S) below the pooler's idle timeout
    (POOLER_IDLE_TIMEOUT_S), so the pool retires a connection before the pooler cuts it.
  * A checkout waits CHECKOUT_TIMEOUT_S (about 3 seconds) at most, and at most MAX_CONCURRENT
    (about 8) BD requests hold a slot at once; the next is refused at once with Busy. Together
    they keep a BD outage from holding the proposal tool's request threads. BD is never part of
    the tool's health check.
  * Every checkout sets, in one round trip: the session time zone UTC, the search_path
    (bd, pg_catalog) and the Central business clock (bd.today / bd.now, which the SQL functions
    bd_today() and bd_now() read, so the view, column defaults and Python agree on "today",
    including under the BD_TODAY test override). Locks, savepoints and row locks are the caller's.
  * The connection string is never logged or put in an error.
  * Under pytest the pool refuses any connection string that is not a test database (a database
    named bd_test_*), so a test can never reach staging or prod.

configure(url) points the pool at another database (the tests do this) and returns what it
pointed at before; close() shuts it. direct(url) is a plain connection for scripts and fixtures.
"""
from __future__ import annotations

import contextlib
import logging
import sys
import threading
from collections.abc import Iterator
from typing import Any

from . import bizdate, config

log = logging.getLogger("bd.db")

CHECKOUT_TIMEOUT_S = 3.0
MAX_CONCURRENT = 8
# The pooler's idle timeout is taken as at least this (Supabase's session pooler; the staging
# Postgres has none). The pool's own limits stay below it.
POOLER_IDLE_TIMEOUT_S = 300.0
MAX_IDLE_S = 120.0
MAX_LIFETIME_S = 240.0
SEARCH_PATH = "bd, pg_catalog"
TEST_DATABASE_PREFIX = "bd_test_"


class Unavailable(Exception):
    """BD's database cannot serve this request now (the routes answer 503)."""


class NotConfigured(Unavailable):
    """BD_DATABASE_URL is not set."""


class Busy(Unavailable):
    """Every BD request slot is taken."""


class RefusedDatabase(RuntimeError):
    """Under pytest, a connection string that is not a test database."""


_lock = threading.Lock()
_pool: Any = None
_url: str | None = None
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)
_slot_state = threading.local()
_in_use = 0
_in_use_lock = threading.Lock()


# ── which database ─────────────────────────────────────────────────────────────────────────────
def database_url() -> str:
    return _url or config.BD_DATABASE_URL


def is_configured() -> bool:
    return bool(database_url())


def configure(url: str | None) -> str | None:
    """Use `url` from now on (None = back to BD_DATABASE_URL). Closes the current pool and returns
    the url set before, so a caller can put it back."""
    global _url
    close()
    with _lock:
        previous, _url = _url, (url or None)
    return previous


def _dbname(url: str) -> str:
    from psycopg import conninfo

    try:
        return str(conninfo.conninfo_to_dict(url).get("dbname") or "")
    except Exception:  # noqa: BLE001  (any unparsable string is simply not a test database)
        return ""


def is_test_database(url: str) -> bool:
    """True for a database the tests made (named bd_test_*)."""
    return bool(url) and _dbname(url).startswith(TEST_DATABASE_PREFIX)


def _under_pytest() -> bool:
    return "pytest" in sys.modules


def _refuse_unless_test_database(url: str) -> None:
    if _under_pytest() and not is_test_database(url):
        raise RefusedDatabase("refusing: under pytest BD's pool only opens a test database (bd_test_*)")


# ── the pool ───────────────────────────────────────────────────────────────────────────────────
def pool_options(url: str) -> dict:
    """The ConnectionPool arguments (tests/test_bd_pool.py pins them)."""
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    low = max(config.BD_DB_POOL_MIN, 0)
    return {
        "conninfo": url,
        "min_size": low,
        "max_size": max(config.BD_DB_POOL_MAX, low, 1),
        "kwargs": {"row_factory": dict_row, "autocommit": False, "connect_timeout": int(CHECKOUT_TIMEOUT_S)},
        "configure": _configure_conn,
        "check": ConnectionPool.check_connection,
        "max_idle": MAX_IDLE_S,
        "max_lifetime": MAX_LIFETIME_S,
        "timeout": CHECKOUT_TIMEOUT_S,
        "open": False,
        "name": "bd",
    }


def _configure_conn(conn: Any) -> None:
    """Once per new physical connection (every checkout sets the session again anyway)."""
    prepare_session(conn)
    conn.commit()


def get_pool() -> Any:
    """The pool, created on first use. NotConfigured when there is no BD_DATABASE_URL."""
    global _pool
    with _lock:
        if _pool is None:
            url = database_url()
            if not url:
                raise NotConfigured("BD's database is not configured (BD_DATABASE_URL is not set)")
            _refuse_unless_test_database(url)
            from psycopg_pool import ConnectionPool

            pool = ConnectionPool(**pool_options(url))
            pool.open(wait=False)
            _pool = pool
        return _pool


def close() -> None:
    global _pool
    with _lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.close()


# ── the session every checkout gets ────────────────────────────────────────────────────────────
def prepare_session(conn: Any) -> None:
    """Time zone UTC, BD's search_path and the business clock, in one round trip."""
    conn.execute(
        "select set_config('TimeZone', 'UTC', false), set_config('search_path', %s, false),"
        " set_config('bd.today', %s, false), set_config('bd.now', %s, false)",
        (SEARCH_PATH, bizdate.today_central().isoformat(), bizdate.now_central().isoformat()))


def set_business_clock(conn: Any) -> None:
    """Copy bizdate's today/now into this session (bd_today(), bd_now() read them)."""
    conn.execute(
        "select set_config('bd.today', %s, false), set_config('bd.now', %s, false)",
        (bizdate.today_central().isoformat(), bizdate.now_central().isoformat()))


# ── the bulkhead ───────────────────────────────────────────────────────────────────────────────
def _slots_in_use() -> int:
    return _in_use


@contextlib.contextmanager
def request_slot() -> Iterator[None]:
    """One of MAX_CONCURRENT BD request slots, or Busy at once. Re-entrant on one thread, so a
    request that holds a slot and then checks out a connection takes one slot, not two."""
    global _in_use
    depth = getattr(_slot_state, "depth", 0)
    if depth:
        _slot_state.depth = depth + 1
        try:
            yield
        finally:
            _slot_state.depth -= 1
        return
    if not _slots.acquire(blocking=False):
        raise Busy("BD is busy; try again in a moment")
    with _in_use_lock:
        _in_use += 1
    _slot_state.depth = 1
    try:
        yield
    finally:
        _slot_state.depth = 0
        with _in_use_lock:
            _in_use -= 1
        _slots.release()


# ── checkouts ──────────────────────────────────────────────────────────────────────────────────
@contextlib.contextmanager
def connect(timeout: float = CHECKOUT_TIMEOUT_S) -> Iterator[Any]:
    """A pooled connection holding one transaction: commit on success, rollback on error.
    Unavailable when the database cannot be reached within `timeout` seconds."""
    from psycopg_pool import PoolTimeout

    with request_slot():
        pool = get_pool()
        with contextlib.ExitStack() as stack:
            try:
                conn = stack.enter_context(pool.connection(timeout=timeout))
            except PoolTimeout:
                log.warning("BD database checkout timed out after %.1fs", timeout)
                raise Unavailable("BD's database did not answer in time") from None
            prepare_session(conn)
            yield conn


def direct(url: str | None = None, autocommit: bool = True) -> Any:
    """A plain (unpooled) connection with dict rows and the same session as a checkout (UTC,
    search_path, business clock): for scripts and test fixtures. The caller closes it."""
    import psycopg
    from psycopg.rows import dict_row

    conn = psycopg.connect(url or database_url(), row_factory=dict_row, autocommit=autocommit)
    prepare_session(conn)
    if not autocommit:
        conn.commit()
    return conn
