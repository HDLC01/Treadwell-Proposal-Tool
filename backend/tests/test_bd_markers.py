"""The BD markers (db, node, e2e) are registered, and tests/_bd_conftest.py puts them on BD tests."""
from __future__ import annotations


def test_the_bd_markers_are_registered(pytestconfig):
    names = {line.split(":", 1)[0].strip() for line in pytestconfig.getini("markers")}
    assert {"db", "node", "e2e"} <= names


def test_a_bd_test_whose_own_code_runs_node_is_marked_node(request):
    """This test's own source names run_node, which is what the plugin looks for."""
    assert "run_node"
    assert request.node.get_closest_marker("node") is not None
    assert request.node.get_closest_marker("db") is None


def test_a_plain_bd_test_carries_no_marker(request):
    for name in ("db", "node", "e2e"):
        assert request.node.get_closest_marker(name) is None, name
