"""A CI run that has lost node must go RED, not green-with-the-frontend-skipped.

About 170 test modules here drive a node harness and carry
`pytest.mark.skipif(shutil.which("node") is None)`. That is the right answer on a laptop with no
node. On a CI runner it is a hole: lose node (an image change, a PATH edit) and every one of those
modules skips, the run reports a pass, and the whole JavaScript half of the product went untested
without a word. Nothing in the suite said "a runner without node is a broken runner".

This file says it. Four parts:

  1. test_node_is_on_the_path_and_recent_enough: the runner has node. Under GITHUB_ACTIONS a missing
     node FAILS here (via tests/_node.require_node); anywhere else it skips, as it always has. This
     is the one test that keeps the 170 old skipif modules from skipping unseen on CI.
  2. the decision itself (fail under CI, skip elsewhere, return the path when it is there), run
     with an injected `which` and environment so it is checked on every machine, node or not.
  3. the new golden tests really use that door. Not read for the string: RUN, in a child pytest with
     node taken off PATH and GITHUB_ACTIONS set, and the child must report failures, not skips.
  4. the child is also run the way a laptop without node would run it (no GITHUB_ACTIONS), and must
     SKIP, so the strictness cannot have leaked into local runs.
"""
import os
import pathlib
import re
import subprocess
import sys

import pytest

from _node import MIN_NODE_MAJOR, node_major, require_node, running_in_ci

HERE = pathlib.Path(__file__).resolve().parent
BACKEND = HERE.parent

# The tests that must use the strict door. test_harness_lib_js.py is a new harness test too, and so
# is test_v2_names.py (its node-free tests, the static pages and the Python sweep, still run).
STRICT_MODULES = ["tests/test_polish_chain_golden.py", "tests/test_library_pricing_golden.py",
                  "tests/test_harness_lib_js.py", "tests/test_v2_names.py"]


# ── 1. the runner has node ───────────────────────────────────────────────────
def test_node_is_on_the_path_and_recent_enough():
    node = require_node()                       # FAILS under CI when node is missing
    assert node_major(node) >= MIN_NODE_MAJOR, (
        "node %d is older than the %d the harnesses are written for" % (node_major(node), MIN_NODE_MAJOR))


# ── 2. the decision ──────────────────────────────────────────────────────────
def _nothing(_name):
    return None


def _outcome(**kw):
    """What require_node did: "fail", "skip", or "returned:<path>". Compared as a plain value so a
    WRONG decision shows up as a failed assertion here, never as this test itself being skipped
    (a Skipped raised out of the code under test would otherwise end the test as a skip)."""
    try:
        return "returned:" + require_node(**kw)
    except pytest.fail.Exception:
        return "fail"
    except pytest.skip.Exception:
        return "skip"


def test_a_missing_node_fails_when_github_actions_is_running_the_tests():
    for value in ("true", "True", "1", "yes"):
        assert _outcome(which=_nothing, environ={"GITHUB_ACTIONS": value}) == "fail", value
    with pytest.raises(pytest.fail.Exception) as seen:
        require_node(which=_nothing, environ={"GITHUB_ACTIONS": "true"})
    assert "CI must have it" in str(seen.value)


def test_a_missing_node_skips_everywhere_else():
    for env in ({}, {"GITHUB_ACTIONS": ""}, {"GITHUB_ACTIONS": "false"}, {"GITHUB_ACTIONS": "0"},
                {"CI": "true"}):                # some OTHER CI, or a developer's own variable: not ours
        assert _outcome(which=_nothing, environ=env) == "skip", env


def test_a_present_node_is_returned_whatever_the_environment_says():
    for env in ({}, {"GITHUB_ACTIONS": "true"}):
        assert _outcome(which=lambda name: "/opt/x/" + name, environ=env) == "returned:/opt/x/node"


def test_running_in_ci_reads_only_github_actions():
    assert running_in_ci({"GITHUB_ACTIONS": "true"}) is True
    assert running_in_ci({"GITHUB_ACTIONS": " TRUE "}) is True
    assert running_in_ci({"GITHUB_ACTIONS": "false"}) is False
    assert running_in_ci({}) is False
    assert running_in_ci({"CI": "true"}) is False


# ── 3 and 4. the golden tests, run without node ─────────────────────────────
def _path_without_node():
    """PATH with every directory that holds a node executable taken out."""
    keep = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        if any((pathlib.Path(entry) / name).exists() for name in ("node", "node.exe", "node.cmd", "node.bat")):
            continue
        keep.append(entry)
    return os.pathsep.join(keep)


def _child_run(ci: bool):
    env = dict(os.environ)
    env["PATH"] = _path_without_node()
    env.pop("GITHUB_ACTIONS", None)
    if ci:
        env["GITHUB_ACTIONS"] = "true"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *STRICT_MODULES, "-q", "-p", "no:cacheprovider",
         "-p", "no:xdist", "--no-header", "--durations=0"],
        cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", timeout=240)
    summary = [ln for ln in proc.stdout.strip().splitlines() if re.search(r"\d+ (passed|failed|skipped|error)", ln)]
    assert summary, "the child pytest printed no summary:\n" + proc.stdout[-1500:] + proc.stderr[-800:]
    text = summary[-1]

    def count(word):
        m = re.search(r"(\d+) " + word, text)
        return int(m.group(1)) if m else 0
    return proc.returncode, count("failed") + count("error"), count("skipped"), count("passed"), text


def test_the_new_tests_fail_rather_than_skip_when_ci_has_no_node():
    require_node()                              # the parent needs node; the child must not have it
    code, bad, skipped, _passed, text = _child_run(ci=True)
    assert code != 0, "the child run went green with no node under CI: " + text
    assert bad > 0, "no failure reported for a missing node under CI: " + text
    assert skipped == 0, "something skipped instead of failing under CI: " + text


def test_the_new_tests_skip_rather_than_fail_when_a_laptop_has_no_node():
    require_node()
    code, bad, skipped, _passed, text = _child_run(ci=False)
    assert skipped > 0, "nothing skipped with no node and no CI: " + text
    assert bad == 0, "a missing node failed a test off CI, which breaks a developer without node: " + text
    assert code == 0, text
