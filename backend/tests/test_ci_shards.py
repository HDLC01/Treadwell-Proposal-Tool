"""The CI shards (.github/scripts/shard_tests.py) and the browser job together run every test file
exactly once.

If a file fell between shards it would never run in CI and nothing would say so, which is the
failure this guards. Executes the real script against the real tests folder, and reads the matrix
and the browser job the workflow really runs. The BD browser suites (test_bd_e2e_*.py, #806) need
Chromium and the live app, so they run in the browser job and in no shard: they count as covered
there.
"""
import importlib.util
import re
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent.parent
SCRIPT = ROOT / ".github" / "scripts" / "shard_tests.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("shard_tests", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def matrix():
    """[(group, shard, total, dist)] as the workflow's matrix lists them."""
    text = WORKFLOW.read_text(encoding="utf-8")
    rows = re.findall(r"-\s*\{\s*group:\s*(\w+),\s*shard:\s*(\d+),\s*total:\s*(\d+),\s*dist:\s*(\w+)\s*\}", text)
    assert rows, "no shard matrix found in ci.yml"
    return [(g, int(s), int(t), d) for g, s, t, d in rows]


BROWSER_RUN = "shard_tests.py browser 1 1 tests"


@pytest.fixture(scope="module")
def browser_files(mod):
    """The files the browser job runs, as the workflow asks the script for them."""
    assert BROWSER_RUN in WORKFLOW.read_text(encoding="utf-8"), "ci.yml's browser job does not ask for them"
    return mod.shard_files(_names(), "browser", 1, 1)


def _names():
    return sorted(p.name for p in TESTS.glob("test_*.py"))


def test_the_shards_and_the_browser_job_cover_every_test_file_exactly_once(mod, matrix, browser_files):
    names = _names()
    seen = list(browser_files)
    for group, shard, total, _ in matrix:
        seen += mod.shard_files(names, group, shard, total)
    assert sorted(seen) == names


def test_the_browser_suites_run_in_the_browser_job_and_in_no_shard(mod, matrix, browser_files):
    """A browser suite in a shard would find no Chromium there and fail; one in neither would never
    run. Every test_bd_e2e_*.py file is the browser job's, and nothing else is."""
    names = _names()
    e2e = [n for n in names if n.startswith("test_bd_e2e_")]
    assert e2e, "vacuity: no BD browser suite in the tests folder"
    assert browser_files == e2e
    assert all(mod.is_browser(n) for n in e2e) and not any(mod.is_heavy(n) for n in e2e)
    for group, shard, total, _ in matrix:
        assert not set(mod.shard_files(names, group, shard, total)) & set(e2e), (group, shard)
    assert "browser" not in {g for g, _, _, _ in matrix}, "the browser group is its own job, not a shard"


def test_every_bd_test_file_lands_in_exactly_one_shard(mod, matrix, browser_files):
    """The BD CRM's tests (#805) sit flat in this folder as test_bd_*.py, because the script only
    looks at the top level: a BD file in a sub-folder would run in no shard. Named on its own so a
    BD file that fell out of the shards is reported as one, not as a diff of the whole suite. The
    browser job counts as one more shard (#806)."""
    bd = [n for n in _names() if n.startswith("test_bd_")]
    assert len(bd) >= 16, bd   # the files #805 moved here; fewer means the glob looks elsewhere
    assert not list(TESTS.glob("*/test_bd_*.py")), "a BD test file in a sub-folder runs in no shard"
    landed = {n: [("browser", 1)] for n in browser_files}
    for group, shard, total, _ in matrix:
        for n in mod.shard_files(_names(), group, shard, total):
            if n.startswith("test_bd_"):
                landed.setdefault(n, []).append((group, shard))
    assert {n: len(v) for n, v in landed.items()} == {n: 1 for n in bd}, landed


def test_each_group_lists_every_one_of_its_shards_once(matrix):
    for group in {g for g, _, _, _ in matrix}:
        rows = [(s, t) for g, s, t, _ in matrix if g == group]
        totals = {t for _, t in rows}
        assert len(totals) == 1, (group, rows)
        assert sorted(s for s, _ in rows) == list(range(1, totals.pop() + 1)), (group, rows)


def test_only_the_heavy_walks_run_spread_by_test(mod, matrix):
    """--dist load re-runs module fixtures per worker and drops file order; only the heavy group
    (no shared module state) may use it, and every other file keeps loadfile."""
    names = _names()
    for group, shard, total, dist in matrix:
        files = mod.shard_files(names, group, shard, total)
        if dist == "load":
            assert group == "heavy" and all(mod.is_heavy(n) for n in files), (group, files)
        else:
            assert dist == "loadfile" and not any(mod.is_heavy(n) for n in files), (group, files)


def test_the_workflow_runs_the_script_with_the_matrix_values():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert ("shard_tests.py ${{ matrix.group }} ${{ matrix.shard }} ${{ matrix.total }} tests"
            in text)
    assert "--dist ${{ matrix.dist }}" in text


def test_the_heaviest_file_is_not_paired_with_much_else(mod, matrix):
    """The ~11-minute answer walk gets a heavy shard nearly to itself (greedy, largest first)."""
    names = _names()
    total = next(t for g, _, t, _ in matrix if g == "heavy")
    loads = []
    for k in range(1, total + 1):
        files = mod.shard_files(names, "heavy", k, total)
        loads.append(sum(mod.HEAVY_COST.get(n, mod.DEFAULT_HEAVY_COST) for n in files))
    assert max(loads) - min(loads) <= max(mod.HEAVY_COST.values()), loads


def test_a_bad_group_or_shard_is_refused(mod):
    with pytest.raises(ValueError):
        mod.shard_files(["test_a.py"], "rest", 0, 5)
    with pytest.raises(ValueError):
        mod.shard_files(["test_a.py"], "rest", 6, 5)
    with pytest.raises(ValueError):
        mod.shard_files(["test_a.py"], "light", 1, 5)
    with pytest.raises(ValueError):
        mod.shard_files(["test_bd_e2e_a.py"], "browser", 2, 1)
