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

The Postgres fixtures (a throwaway database per xdist worker, migrated by the runner) arrive with
the database stage of #805.
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
_DB_FIXTURES = {"db", "db_url", "_db_conn", "client", "as_user", "seeded"}
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
