"""Finding node, and what a test does when it is not there.

THE OLD RULE, STILL TRUE ON A LAPTOP. About 170 test modules drive a node harness and carry
`pytest.mark.skipif(shutil.which("node") is None)`: "skipped when node isn't installed; it's on the
dev box and in the Docker image". On a machine that has no node, skipping is the polite answer.

THE PROBLEM, ON CI. The same marker means a CI runner that LOST node (an image change, a runner
swap, a PATH edit) goes green while every one of those modules quietly skips: the suite reports a
pass for the whole JavaScript half of the product without having run any of it. Nothing would say so.

THE RULE FOR NEW TESTS (the v2 characterization program onward): call `require_node()`. Missing
node FAILS the test when GitHub Actions is running it (the runner sets GITHUB_ACTIONS) and SKIPS it
anywhere else. test_node_strict.py checks the door itself, checks that CI really has a node, and
runs the golden tests with node taken off the path to watch them fail rather than skip. The old
modules are not rewritten; that one test is what keeps them from skipping unseen on CI.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

# The floor the harnesses are written for (Object.fromEntries, fs.rmSync, String.startsWith). The
# Docker image and the CI runner are both well above it.
MIN_NODE_MAJOR = 18


def running_in_ci(environ=None) -> bool:
    """True when GitHub Actions is running this. `GITHUB_ACTIONS` is "true" there and unset
    everywhere else; an explicit "false" or "0" is read as not-CI so a developer can say so."""
    env = os.environ if environ is None else environ
    return str(env.get("GITHUB_ACTIONS", "")).strip().lower() not in ("", "0", "false", "no")


def require_node(which=shutil.which, environ=None) -> str:
    """The path of node, or the end of the test: FAIL under CI, SKIP anywhere else."""
    path = which("node")
    if path:
        return path
    if running_in_ci(environ):
        pytest.fail("node is not on PATH, and CI must have it: every JavaScript harness in this "
                    "suite needs it, and skipping them would pass a run that tested none of the "
                    "frontend. Fix the runner image or its PATH.", pytrace=False)
    pytest.skip("node is not installed")


def node_major(node: str) -> int:
    """The major version of the node at `node`, e.g. 24 for v24.13.1."""
    proc = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30)
    match = re.match(r"v(\d+)\.", proc.stdout.strip())
    if proc.returncode != 0 or not match:
        raise RuntimeError("could not read the node version from %r %r" % (proc.stdout, proc.stderr))
    return int(match.group(1))


def run_node(script, *args, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run `node script args...` and return the finished process (stdout and stderr as text).
    Fails or skips through require_node() when there is no node."""
    node = require_node()
    return subprocess.run([node, str(script), *[str(a) for a in args]], capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout)


def last_json_line(stdout: str):
    """The harness convention: everything is printed, the last line is the JSON answer."""
    lines = [ln for ln in stdout.strip().splitlines() if ln.strip()]
    assert lines, "the harness printed nothing"
    return json.loads(lines[-1])
