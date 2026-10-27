"""Print the test files one CI shard runs: `python shard_tests.py <heavy|rest> <shard 1..N> <N> [tests_dir]`.

Every file lands in exactly ONE shard of ONE group, so the shards together run the whole suite and
nothing twice (backend/tests/test_ci_shards.py asserts the union and the disjointness).

WHY TWO GROUPS (2026-10-27). The suite runs `--dist loadfile`, which keeps a file on one core.
That was the bottleneck: test_polish_travel_sequences_answer.py alone is about 11 minutes, so its
shard could never finish sooner however many shards there were. The polish-travel sequence walks
have no shared module state worth keeping (each test spawns its own node process), so:

  * HEAVY: the test_polish_travel_sequences*.py files, split across HEAVY_SHARDS shards by their
    measured cost (greedy, largest first) and run with `--dist load`, which spreads their single
    tests over every core;
  * REST: every other file, dealt round-robin by name and run with `--dist loadfile` as before
    (module fixtures built once, tests/test_leads.py's order kept).

HEAVY_COST holds seconds measured from CI's slowest-25 lists (run 40515022917). A heavy file not
listed costs DEFAULT_HEAVY_COST. If another family of files turns slow, add its prefix to
HEAVY_PREFIXES and its cost here.
"""
import sys
from pathlib import Path

HEAVY_PREFIXES = ("test_polish_travel_sequences",)
DEFAULT_HEAVY_COST = 60.0
HEAVY_COST = {
    "test_polish_travel_sequences_answer.py": 649,
    "test_polish_travel_sequences_owned.py": 217,
    "test_polish_travel_sequences_session_mutations.py": 183,
    "test_polish_travel_sequences_mutations.py": 182,
    "test_polish_travel_sequences_reload.py": 154,
    "test_polish_travel_sequences_session_local.py": 124,
    "test_polish_travel_sequences.py": 119,
    "test_polish_travel_sequences_distance.py": 118,
    "test_polish_travel_sequences_reload_more.py": 89,
    "test_polish_travel_sequences_session.py": 83,
}
GROUPS = ("heavy", "rest")


def is_heavy(name):
    return name.startswith(HEAVY_PREFIXES)


def shard_files(names, group, shard, total):
    """The file names (sorted) that shard `shard` of `total` (1-based) in `group` runs."""
    if group not in GROUPS:
        raise ValueError("group must be one of %s" % (GROUPS,))
    if not (1 <= shard <= total):
        raise ValueError("shard must be between 1 and %d" % total)
    names = sorted(names)
    if group == "rest":
        rest = [n for n in names if not is_heavy(n)]
        return [n for i, n in enumerate(rest) if i % total == shard - 1]
    # Greedy longest-first: each file goes to the shard with the least cost so far (ties: lowest
    # shard, then name order), so the split is the same on every runner.
    heavy = sorted((n for n in names if is_heavy(n)),
                   key=lambda n: (-HEAVY_COST.get(n, DEFAULT_HEAVY_COST), n))
    loads = [0.0] * total
    owner = {}
    for n in heavy:
        k = min(range(total), key=lambda i: (loads[i], i))
        owner[n] = k
        loads[k] += HEAVY_COST.get(n, DEFAULT_HEAVY_COST)
    return sorted(n for n in heavy if owner[n] == shard - 1)


def test_file_names(tests_dir):
    return [p.name for p in Path(tests_dir).glob("test_*.py")]


if __name__ == "__main__":
    group, shard, total = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    tests_dir = sys.argv[4] if len(sys.argv) > 4 else "tests"
    for name in shard_files(test_file_names(tests_dir), group, shard, total):
        print("%s/%s" % (tests_dir, name))
