"""The BD CRM's test setup, loaded as a plugin by tests/conftest.py (`pytest_plugins`).

BD's tests sit flat in this folder as test_bd_*.py (the CI shard script only looks at the top
level), and its helpers carry a _bd prefix. What BD's own conftest did comes over here, so none of
it leaks into the proposal tool's tests:

1. MARKERS (registered in backend/pytest.ini). Every BD test is marked here, so nobody has to
   remember to:
     db    the test (or a fixture it uses) needs Postgres
     node  the test's own code runs node (tests/_node.py)
     e2e   a real-browser suite (tests/test_bd_e2e_*.py)
   Only BD test files (test_bd_*.py) are marked; the proposal tool's tests are left as they are.

2. HYPOTHESIS. On CI the property tests (test_bd_props_*.py) are deterministic (a failure
   reproduces from the commit alone) and never write a .hypothesis/ database; locally they explore
   randomly and keep the database, so a found counter-example is replayed first. No deadline
   either way: a test that starts node is slow on purpose.

3. POSTGRES (tests/_bd_db.py has the helpers and the rules for sharing one server):
     bd_admin         (session)  BD_TEST_DATABASE_URL, an ADMIN url on a throwaway Postgres 16.
                                 Unset: SKIP locally, FAIL on CI.
     bd_migrated_url  (module)   a database of the module's own, migrated by the runner
                                 (backend/bd/migrate.py), dropped at the end. The bd_app-like test
                                 login exists; _bd_db.app_login_url(url) connects as it.
     bd_owner         (function) an admin connection on that database (dict rows, search_path
                                 bd, pg_catalog) inside a transaction that is rolled back afterwards.

4. THE APP'S DATABASE (BD's own conftest fixtures, renamed with a bd_ prefix so they never mix with
   the proposal tool's db / client / as_user):
     bd_db_url   (session)  ONE database per xdist worker (bd_test_<worker>_<rand>), migrated by the
                            runner, dropped at the end. BD's pool (backend/bd/db.py) is pointed at it
                            as the bd_app-like login, never the owner, so a missing grant or policy
                            fails the test. Yields the database's ADMIN url (for a test that must
                            act as the owner, e.g. to kill a backend).
     bd_db       (function) every BD table emptied (ids restart at 1), then a plain autocommit
                            connection as the bd_app-like login (dict rows, UTC, search_path, the
                            business clock set). After bd_today moves "today" it is updated for you.
     bd_today    (function) bd_today("2026-11-04") sets BD_TODAY for this test (and the open
                            fixture connections); bd_today(None) clears it. Returns the date set.
     bd_seeded   (function) bd_db + the fixture seed (backend/bd/ops/fixture_seed.py) +
                            BD_TODAY = its day. Returns {"counts": ..., "today": date}.
   BD_TEST_DATABASE_URL unset: SKIP locally, FAIL on CI (as above).
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

from _node import running_in_ci

BD_TEST_PREFIX = "test_bd_"
BD_E2E_PREFIX = "test_bd_e2e_"

# The fixtures that reach Postgres, named here before they exist so a test that asks for one is
# marked the moment the fixture arrives; and the words in a test's own code that mean it runs node.
_DB_FIXTURES = {"db", "db_url", "_db_conn", "client", "as_user", "seeded",
                "bd_admin", "bd_migrated_url", "bd_owner",
                "bd_db_url", "_bd_db_conn", "bd_db", "bd_seeded"}
_NODE_WORDS = ("run_node", "require_node", "run_steps", "_node.")


def is_bd_test_file(path) -> bool:
    return pathlib.Path(str(path)).name.startswith(BD_TEST_PREFIX)


def pytest_collection_modifyitems(config, items):
    for item in items:
        path = pathlib.Path(str(item.fspath))
        if not is_bd_test_file(path):
            continue
        fixtures = set(getattr(item, "fixturenames", ()))
        if path.name.startswith(BD_E2E_PREFIX):
            item.add_marker(pytest.mark.e2e)
        if fixtures & _DB_FIXTURES:
            item.add_marker(pytest.mark.db)
        if getattr(item, "function", None) is not None:
            try:
                src = inspect.getsource(item.function)
            except (OSError, TypeError):
                src = ""
            if any(word in src for word in _NODE_WORDS):
                item.add_marker(pytest.mark.node)


try:
    from hypothesis import HealthCheck, settings
except ImportError:   # hypothesis is a dev dependency; the production image never runs tests
    pass
else:
    settings.register_profile("bd-ci", derandomize=True, database=None, deadline=None, max_examples=100,
                              suppress_health_check=[HealthCheck.too_slow])
    settings.register_profile("bd-dev", deadline=None, max_examples=100)
    settings.load_profile("bd-ci" if running_in_ci() else "bd-dev")


# -- Postgres ---------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def bd_admin():
    import _bd_db

    return _bd_db.admin_url()


@pytest.fixture(scope="module")
def bd_migrated_url(bd_admin):
    import _bd_db

    _bd_db.ensure_app_login(bd_admin)
    with _bd_db.new_database(bd_admin) as url:
        with _bd_db.cluster_lock(bd_admin, exclusive=False):
            _bd_db.migrate(url)
        yield url


@pytest.fixture
def bd_owner(bd_migrated_url):
    import _bd_db
    from psycopg.rows import dict_row

    conn = _bd_db.connect(bd_migrated_url, autocommit=False, row_factory=dict_row)
    try:
        conn.execute("set search_path = bd, pg_catalog")
        yield conn
    finally:
        conn.rollback()
        conn.close()


# -- the app's database: one per xdist worker ---------------------------------------------------
_OPEN_CONNS: list = []


@pytest.fixture(scope="session")
def bd_db_url(bd_admin):
    import _bd_db
    from bd import db as dbmod

    _bd_db.ensure_app_login(bd_admin)
    with _bd_db.new_database(bd_admin) as url:
        with _bd_db.cluster_lock(bd_admin, exclusive=False):
            _bd_db.migrate(url)
        previous = dbmod.configure(_bd_db.app_login_url(url))
        try:
            yield url
        finally:
            dbmod.configure(previous)
            dbmod.close()


@pytest.fixture(scope="session")
def _bd_db_conn(bd_db_url):
    """One autocommit connection per session as the bd_app-like login, reused by every bd_db
    (opening one costs more than the reset)."""
    import _bd_db
    from bd import db as dbmod

    conn = dbmod.direct(_bd_db.app_login_url(bd_db_url), autocommit=True)
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def bd_db(_bd_db_conn):
    from bd import db as dbmod
    from bd.ops import fixture_seed

    conn = _bd_db_conn
    if conn.info.transaction_status != 0:      # a test left a transaction open: end it
        conn.rollback()
    fixture_seed.reset_data(conn)
    dbmod.prepare_session(conn)
    _OPEN_CONNS.append(conn)
    try:
        yield conn
    finally:
        _OPEN_CONNS.remove(conn)


@pytest.fixture
def bd_today(monkeypatch):
    import datetime as dt

    from bd import bizdate
    from bd import db as dbmod

    def set_today(value):
        if value is None:
            monkeypatch.delenv("BD_TODAY", raising=False)
        else:
            monkeypatch.setenv("BD_TODAY", value.isoformat() if isinstance(value, dt.date) else str(value))
        for conn in list(_OPEN_CONNS):
            dbmod.set_business_clock(conn)
        return bizdate.today_central()

    yield set_today
    monkeypatch.delenv("BD_TODAY", raising=False)


@pytest.fixture
def bd_seeded(bd_db, bd_today):
    from bd.ops import fixture_seed

    day = bd_today(fixture_seed.FIXTURE_TODAY)
    counts = fixture_seed.seed(bd_db)
    return {"counts": counts, "today": day}
