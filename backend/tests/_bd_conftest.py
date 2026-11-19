"""The BD CRM's test setup, loaded as a plugin by tests/conftest.py (`pytest_plugins`).

BD's tests sit flat in this folder as test_bd_*.py (the CI shard script only looks at the top
level), and its helpers carry a _bd prefix. What BD's own conftest did comes over here. The markers
and the fixtures touch only BD's tests; the Hypothesis profile (2.) is the one setting that applies
to the whole run:

1. MARKERS (registered in backend/pytest.ini). Every BD test is marked here, so nobody has to
   remember to:
     db    the test (or a fixture it uses) needs Postgres
     node  the test's own code runs node (tests/_node.py)
     e2e   a real-browser suite (tests/test_bd_e2e_*.py)
   Only BD test files (test_bd_*.py) are marked; the proposal tool's tests are left as they are.
   db comes from the bd_* database fixtures below and nothing else: the proposal tool's own
   per-module client / as_user / db fixtures never touch Postgres, so a BD test using them is not
   a database test. node is read from the test function's own source (a call to the node helpers),
   as BD's conftest did; markers_for() is the whole rule and test_bd_markers.py pins it.

2. HYPOTHESIS, for EVERY test in the run that uses it (today only BD's test_bd_props_*.py). On CI
   the property tests are deterministic (a failure reproduces from the commit alone) and never
   write a .hypothesis/ database; locally they explore randomly and keep the database, so a found
   counter-example is replayed first. No deadline either way: a test that starts node is slow on
   purpose. A test that needs other settings says so with its own @settings.

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

5. THE APP (#806): BD's routes on the proposal tool's app, signed in the way the tool signs in.
     bd_app       (function) the tool's app with BD_ENABLED on, the tool's verify step
                             (supabase_client.verify_identity) overridden to accept
                             "Bearer test:<email>", the sidebar policy files in tmp_path, and every
                             caller a plain proposal-tool "user" unless bd_app.tool_roles says
                             otherwise ({email: role}). No database.
     bd_client    (function) a TestClient over that app on the clean BD database (bd_db).
                             raise_server_exceptions=False, so a 500 is an answer.
     bd_as_user   (function) bd_as_user(1) / bd_as_user("assistant") / bd_as_user("x@example.com")
                             -> a client whose requests carry that BD login's test token, with
                             .user (the bd.users row). A role nobody holds gets "Test <Role>".
   THE TOOL'S GATE, NAV GATE AND AUDIT LOG RUN FOR REAL. Only the verify step is replaced, which is
   the one thing that would need Supabase; tests/test_bd_token_tampering.py runs the real one.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

from _node import running_in_ci

BD_TEST_PREFIX = "test_bd_"
BD_E2E_PREFIX = "test_bd_e2e_"

# BD's fixtures that reach Postgres (all defined below), and the words in a test's own code that
# mean it runs node.
_DB_FIXTURES = {"bd_admin", "bd_migrated_url", "bd_owner", "bd_db_url", "_bd_db_conn", "bd_db", "bd_seeded"}
_NODE_WORDS = ("run_node", "require_node", "run_steps", "_node.")


def is_bd_test_file(path) -> bool:
    return pathlib.Path(str(path)).name.startswith(BD_TEST_PREFIX)


def markers_for(path, fixturenames, function) -> set:
    """The BD markers a test gets: its file's name, the fixtures it uses and its own source."""
    name = pathlib.Path(str(path)).name
    if not is_bd_test_file(name):
        return set()
    marks = set()
    if name.startswith(BD_E2E_PREFIX):
        marks.add("e2e")
    if set(fixturenames) & _DB_FIXTURES:
        marks.add("db")
    if function is not None:
        try:
            src = inspect.getsource(function)
        except (OSError, TypeError):
            src = ""
        if any(word in src for word in _NODE_WORDS):
            marks.add("node")
    return marks


def pytest_collection_modifyitems(config, items):
    for item in items:
        for mark in sorted(markers_for(item.fspath, getattr(item, "fixturenames", ()),
                                       getattr(item, "function", None))):
            item.add_marker(getattr(pytest.mark, mark))


try:
    from hypothesis import HealthCheck, settings
except ImportError:   # hypothesis is a dev dependency; the production image never runs tests
    pass
else:
    # Suite-wide (see 2. above), so named for the run, not for BD.
    settings.register_profile("suite-ci", derandomize=True, database=None, deadline=None, max_examples=100,
                              suppress_health_check=[HealthCheck.too_slow])
    settings.register_profile("suite-dev", deadline=None, max_examples=100)
    settings.load_profile("suite-ci" if running_in_ci() else "suite-dev")


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


# -- the app: the proposal tool's, with BD switched on (#806) -----------------------------------
BD_TOKEN_PREFIX = "test:"
BD_ROLES = ("salesperson", "assistant", "manager", "admin", "super_admin")


def fake_verify_identity(authorization):
    """The test stand-in for the tool's verify step: "Bearer test:<email>" -> that identity.
    Anything else is refused the way the real step refuses a bad token."""
    import supabase_client

    raw = str(authorization or "")
    if not raw.lower().startswith("bearer "):
        raise supabase_client.AuthError(401, "Missing bearer token.")
    token = raw.split(" ", 1)[1].strip()
    if not token.startswith(BD_TOKEN_PREFIX) or "@" not in token:
        raise supabase_client.AuthError(401, "Invalid or expired token.")
    email = token[len(BD_TOKEN_PREFIX):].strip().lower()
    return {"email": email, "sub": "test-" + email, "name": None}


def bd_token_headers(email):
    return {"Authorization": "Bearer " + BD_TOKEN_PREFIX + email}


@pytest.fixture
def bd_app(monkeypatch, tmp_path):
    import types

    import main
    import nav_access
    import special_permissions
    import supabase_client
    from bd import config as bd_config

    monkeypatch.setattr(supabase_client, "verify_identity", fake_verify_identity)
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    for mod in (nav_access, special_permissions):
        monkeypatch.setattr(mod, "_DATA_DIR", tmp_path)
        monkeypatch.setattr(mod, "_FILE", tmp_path / mod._FILE.name)
    tool_roles: dict = {}
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda email: {"id": "p-" + str(email), "email": email,
                                       "role": tool_roles.get(email, "user"), "status": "active"})
    main._profile_cache_clear()
    return types.SimpleNamespace(app=main.app, tool_roles=tool_roles)


@pytest.fixture
def bd_client(bd_app, bd_db):
    from fastapi.testclient import TestClient

    return TestClient(bd_app.app, raise_server_exceptions=False)


class BDAuthedClient:
    """A TestClient whose every request carries the test token of one BD login."""

    def __init__(self, client, user):
        self.client = client
        self.user = user
        self.headers = bd_token_headers(user["email"])

    def request(self, method, path, **kw):
        headers = dict(self.headers)
        headers.update(kw.pop("headers", None) or {})
        return self.client.request(method, path, headers=headers, **kw)

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def put(self, path, **kw):
        return self.request("PUT", path, **kw)

    def patch(self, path, **kw):
        return self.request("PATCH", path, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)


@pytest.fixture
def bd_as_user(bd_client, bd_db):
    def sign_in(who):
        key = str(who).strip().lower()
        if isinstance(who, int) or key.isdigit():
            row = bd_db.execute("select * from bd.users where id = %s", (int(key),)).fetchone()
        elif "@" in key:
            row = bd_db.execute("select * from bd.users where email = %s", (key,)).fetchone()
        elif key in BD_ROLES:
            row = bd_db.execute("select * from bd.users where role = %s and active order by id limit 1",
                                (key,)).fetchone()
            if row is None:
                label = key.replace("_", " ").title()
                row = bd_db.execute(
                    "insert into bd.users (email, name, role) values (%s, %s, %s) returning *",
                    ("test.%s@example.com" % key.replace("_", "."), "Test " + label, key)).fetchone()
        else:
            row = bd_db.execute("select * from bd.users where lower(name) = %s order by id limit 1",
                                (key,)).fetchone()
        if row is None:
            raise LookupError("no BD login %r in the test database (seed it, or use a role name)" % (who,))
        return BDAuthedClient(bd_client, dict(row))

    return sign_in
