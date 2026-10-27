"""Print the test files one CI shard runs: `python shard_tests.py <shard 1..N> <N> [tests_dir]`.

Every file lands in exactly ONE shard, so the shards together run the whole suite and nothing
twice. The split is by FILE (the suite already runs with `--dist loadfile`, which assumes files
are independent of each other), and it is dealt round-robin in two groups so the slow files are
spread out instead of landing on one runner:

  * the polish-travel sequence walks (test_polish_travel_sequences*.py) are the heaviest files by
    far (about a third of the suite's CPU time, single tests of 1 to 4 minutes), so they are dealt
    out first, one per shard in turn;
  * everything else is dealt out second, starting where the heavy files stopped.

File SIZE is no guide to cost here (a 1.7 KB file is among the slowest), which is why the heavy
group is named rather than measured. If another family of files turns slow, add its prefix to
HEAVY_PREFIXES.

backend/tests/test_ci_shards.py asserts the union and the disjointness.
"""
import sys
from pathlib import Path

HEAVY_PREFIXES = ("test_polish_travel_sequences",)


def shard_files(names, shard, total):
    """The file names (sorted) that shard `shard` of `total` (1-based) runs."""
    if not (1 <= shard <= total):
        raise ValueError("shard must be between 1 and %d" % total)
    names = sorted(names)
    heavy = [n for n in names if n.startswith(HEAVY_PREFIXES)]
    rest = [n for n in names if not n.startswith(HEAVY_PREFIXES)]
    mine = [n for i, n in enumerate(heavy) if i % total == shard - 1]
    offset = len(heavy)
    mine += [n for i, n in enumerate(rest) if (i + offset) % total == shard - 1]
    return sorted(mine)


def test_file_names(tests_dir):
    return [p.name for p in Path(tests_dir).glob("test_*.py")]


if __name__ == "__main__":
    shard, total = int(sys.argv[1]), int(sys.argv[2])
    tests_dir = sys.argv[3] if len(sys.argv) > 3 else "tests"
    for name in shard_files(test_file_names(tests_dir), shard, total):
        print("%s/%s" % (tests_dir, name))
