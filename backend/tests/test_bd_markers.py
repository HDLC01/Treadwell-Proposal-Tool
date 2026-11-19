"""The BD markers (db, node, e2e) are registered, and tests/_bd_conftest.py puts them on BD tests."""
from __future__ import annotations

import _bd_conftest


def test_the_bd_markers_are_registered(pytestconfig):
    names = {line.split(":", 1)[0].strip() for line in pytestconfig.getini("markers")}
    assert {"db", "node", "e2e"} <= names


# Stand-ins for test functions, classified below and never called.
def _a_test_that_runs_node():
    from _node import run_node

    run_node("never-run.js")


def _a_plain_test():
    assert 1 + 1 == 2


def test_a_bd_test_whose_own_code_runs_node_is_marked_node():
    assert _bd_conftest.markers_for("test_bd_x.py", (), _a_test_that_runs_node) == {"node"}


def test_a_bd_test_that_uses_a_bd_database_fixture_is_marked_db():
    for fixture in ("bd_admin", "bd_migrated_url", "bd_owner", "bd_db_url", "_bd_db_conn", "bd_db",
                    "bd_seeded"):
        assert _bd_conftest.markers_for("test_bd_x.py", ("tmp_path", fixture), _a_plain_test) == {"db"}, fixture


def test_the_proposal_tools_own_fixture_names_never_mark_a_bd_test_db():
    """A BD route test written the tool's way (a per-module client / as_user / db that never touches
    Postgres) must not be marked db, or `-m "not db"` would drop it."""
    for fixture in ("db", "db_url", "client", "as_user", "seeded"):
        assert _bd_conftest.markers_for("test_bd_x.py", (fixture,), _a_plain_test) == set(), fixture


def test_a_bd_browser_suite_is_marked_e2e():
    assert _bd_conftest.markers_for("test_bd_e2e_pages.py", (), _a_plain_test) == {"e2e"}


def test_only_bd_test_files_are_marked():
    assert _bd_conftest.markers_for("test_leads.py", ("bd_db",), _a_test_that_runs_node) == set()


def test_a_plain_bd_test_carries_no_marker(request):
    assert _bd_conftest.markers_for("test_bd_x.py", ("request",), _a_plain_test) == set()
    for name in ("db", "node", "e2e"):
        assert request.node.get_closest_marker(name) is None, name
