"""CI runs the BD browser suites in a job of their own, and the required gate needs it (#806, Q28).

The suites (tests/test_bd_e2e_*.py) drive a real Chromium against the live app: tests/_bd_browser.py
makes a BD test database on the job's Postgres 16, migrates and seeds it, and starts uvicorn on it
with BD switched on. They FAIL on CI when Playwright, its Chromium or the database is missing, so the
job must install and start all three. Reads the workflow GitHub really runs.
"""
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DEV_REQUIREMENTS = ROOT / "backend" / "requirements-dev.txt"


@pytest.fixture(scope="module")
def wf():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    if True in data:                       # YAML 1.1 reads the bare key `on:` as True
        data["on"] = data.pop(True)
    return data


@pytest.fixture(scope="module")
def job(wf):
    assert "browser" in wf["jobs"], "ci.yml has no browser job"
    return wf["jobs"]["browser"]


def _step(job, name):
    steps = [s for s in job["steps"] if s.get("name") == name]
    assert len(steps) == 1, (name, [s.get("name") for s in job["steps"]])
    return steps[0]


def _runs(job):
    return "\n".join(str(s.get("run", "")) for s in job["steps"])


def test_the_required_gate_needs_the_browser_job_and_fails_without_it(wf):
    gate = wf["jobs"]["test"]
    assert "browser" in gate["needs"]
    assert gate.get("if") == "always()", "the gate must run, and fail, when the browser job fails"
    script = _runs(gate)
    assert re.search(r'test "\$\{\{ needs\.browser\.result \}\}" = "success"', script), script
    assert re.search(r'test "\$\{\{ needs\.shard\.result \}\}" = "success"', script), script


def test_it_skips_with_the_shards_on_a_tree_that_already_passed(job):
    assert job["needs"] == "fingerprint"
    gated = [s for s in job["steps"] if "Reusing" not in str(s.get("name", ""))]
    for s in gated:
        assert s.get("if") == "needs.fingerprint.outputs.skip != 'true'", s.get("name") or s.get("uses")
    reuse = [s for s in job["steps"] if "Reusing" in str(s.get("name", ""))]
    assert len(reuse) == 1 and reuse[0]["if"] == "needs.fingerprint.outputs.skip == 'true'"
    assert reuse[0].get("working-directory") == "."


def test_it_starts_the_same_postgres_16_as_the_shards(wf, job):
    assert job["services"]["postgres"] == wf["jobs"]["shard"]["services"]["postgres"]


def test_it_hands_the_suites_the_same_admin_url_as_the_shards(wf, job):
    shard_run = [s for s in wf["jobs"]["shard"]["steps"] if s.get("name") == "Run tests"][0]
    env = _step(job, "Run the browser suites")["env"]
    assert env["BD_TEST_DATABASE_URL"] == shard_run["env"]["BD_TEST_DATABASE_URL"]
    assert str(env["BD_ENABLED"]) == "on"


def test_it_installs_the_pinned_playwright_and_its_chromium(job):
    assert _step(job, "Install dependencies")["run"].strip() == "pip install -r requirements-dev.txt"
    install = _step(job, "Install Chromium for the browser suites")["run"].strip()
    # The version comes from the playwright package pinned in requirements-dev.txt, so the
    # browser always matches the library.
    assert install == "python -m playwright install --with-deps chromium"
    order = [s.get("name") for s in job["steps"]]
    assert order.index("Install dependencies") < order.index("Install Chromium for the browser suites") \
        < order.index("Run the browser suites")


def test_playwright_is_pinned_exactly_in_the_dev_requirements():
    pins = [ln.split("#")[0].strip() for ln in DEV_REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if ln.strip().lower().startswith("playwright")]
    assert len(pins) == 1 and re.fullmatch(r"playwright==\d+\.\d+\.\d+", pins[0]), pins


def test_it_runs_exactly_the_browser_files_and_refuses_an_empty_list(job):
    step = _step(job, "Run the browser suites")
    run = step["run"]
    assert "shard_tests.py browser 1 1 tests" in run
    # An empty list would make pytest fall back to `testpaths` and run the whole suite here.
    assert re.search(r'if \[ -z "\$FILES" \]; then', run) and "exit 1" in run, run
    assert "python -m pytest $FILES" in run
    assert "set -euo pipefail" in run


def test_it_sets_up_python_3_11_like_the_shards(wf, job):
    def py(j):
        return [s for s in j["steps"] if str(s.get("uses", "")).startswith("actions/setup-python@")]
    mine, theirs = py(job), py(wf["jobs"]["shard"])
    assert len(mine) == 1 and mine[0]["uses"] == theirs[0]["uses"]
    assert str(mine[0]["with"]["python-version"]) == "3.11"
    assert job["defaults"]["run"]["working-directory"] == "backend"


def test_it_reads_no_secret_and_asks_for_read_only_contents(job):
    assert "secrets." not in str(job)
    assert job["permissions"] == {"contents": "read"}
