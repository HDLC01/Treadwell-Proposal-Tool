"""The CI chunks (.github/scripts/shard_tests.py) together run every test file exactly once.

If a file fell between chunks it would never run in CI and nothing would say so, which is the
failure this guards. Executes the real script against the real tests folder.
"""
import importlib.util
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
SCRIPT = TESTS.parent.parent / ".github" / "scripts" / "shard_tests.py"
TOTAL = 4  # the matrix in .github/workflows/ci.yml


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("shard_tests", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _names():
    return sorted(p.name for p in TESTS.glob("test_*.py"))


def test_the_chunks_cover_every_test_file_exactly_once(mod):
    names = _names()
    seen = []
    for k in range(1, TOTAL + 1):
        seen += mod.shard_files(names, k, TOTAL)
    assert sorted(seen) == names


def test_the_workflow_runs_as_many_chunks_as_the_script_splits_into():
    text = (TESTS.parent.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "shard: [1, 2, 3, 4]" in text
    assert "shard_tests.py ${{ matrix.shard }} %d tests" % TOTAL in text


def test_the_heavy_walks_are_spread_not_piled_on_one_chunk(mod):
    names = _names()
    heavy = [n for n in names if n.startswith(mod.HEAVY_PREFIXES)]
    assert len(heavy) >= TOTAL
    per_chunk = [sum(1 for n in mod.shard_files(names, k, TOTAL) if n in heavy)
                 for k in range(1, TOTAL + 1)]
    assert max(per_chunk) - min(per_chunk) <= 1, per_chunk


def test_a_chunk_outside_the_range_is_refused(mod):
    with pytest.raises(ValueError):
        mod.shard_files(["test_a.py"], 0, TOTAL)
    with pytest.raises(ValueError):
        mod.shard_files(["test_a.py"], TOTAL + 1, TOTAL)
