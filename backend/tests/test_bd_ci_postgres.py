"""CI gives the BD database tests a real Postgres 16 (#805).

The BD Postgres fixtures (tests/_bd_conftest.py, tests/_bd_db.py) read BD_TEST_DATABASE_URL, an
ADMIN url on a throwaway server, and FAIL on CI when it is unset. So the workflow has to start that
server and hand the tests its address, on the shard job that already runs the suite. #806 adds one
job, the browser suites' (tests/test_bd_ci_browser.py), and the required `test` gate needs it, so
branch protection still requires one check. This reads the workflow GitHub really runs.
"""
import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# The jobs ci.yml had before #805. #805 added none; #806 adds the browser job, which the `test`
# gate needs, so `test` stays the one required check.
JOBS_BEFORE_BD = {"fingerprint", "shard", "test", "audit"}
BD_JOBS = {"browser"}


@pytest.fixture(scope="module")
def wf():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    if True in data:                       # YAML 1.1 reads the bare key `on:` as True
        data["on"] = data.pop(True)
    return data


@pytest.fixture(scope="module")
def shard(wf):
    return wf["jobs"]["shard"]


@pytest.fixture(scope="module")
def postgres(shard):
    services = shard.get("services") or {}
    assert "postgres" in services, "the shard job starts no Postgres service"
    return services["postgres"]


def _run_tests_step(shard):
    steps = [s for s in shard["steps"] if s.get("name") == "Run tests"]
    assert len(steps) == 1, [s.get("name") for s in shard["steps"]]
    return steps[0]


def _test_url(shard):
    """BD_TEST_DATABASE_URL as the Run tests step sees it (its own env, else the job's)."""
    step_env = _run_tests_step(shard).get("env", {})
    return step_env.get("BD_TEST_DATABASE_URL") or shard.get("env", {}).get("BD_TEST_DATABASE_URL")


def test_the_only_new_job_is_the_browser_job_and_the_required_gate_needs_it(wf):
    assert set(wf["jobs"]) == JOBS_BEFORE_BD | BD_JOBS
    assert wf["jobs"]["test"]["needs"] == ["shard", "browser"]


def test_the_shard_job_starts_postgres_16_pinned_by_digest(postgres):
    image = postgres["image"]
    assert re.fullmatch(r"postgres:16(\.\d+)?-alpine@sha256:[0-9a-f]{64}", image), image


def test_the_admin_is_not_named_after_the_bd_schema(postgres):
    """Postgres's default search_path is `"$user", public`. An admin called `bd` puts schema bd
    first on every admin connection, so whatever the tests create unqualified (an extension's
    functions, a probe table meant for public) lands inside bd, and the privilege and ledger tests
    fail on objects BD never made. Seen locally on the first run of this job's settings."""
    assert postgres["env"]["POSTGRES_USER"] not in ("bd", "bd_app")


def test_the_service_is_healthy_before_the_tests_start(postgres):
    options = postgres.get("options", "")
    assert "--health-cmd" in options and "pg_isready" in options, options


def test_bd_test_database_url_points_at_that_service_as_its_admin(shard, postgres):
    url = _test_url(shard)
    assert url, "the Run tests step does not set BD_TEST_DATABASE_URL"
    u = urlsplit(url)
    assert u.scheme in ("postgresql", "postgres"), url
    parts = {"user": u.username, "password": u.password, "dbname": u.path.lstrip("/"),
             "host": u.hostname, "port": str(u.port or 5432)}
    env = postgres["env"]
    # Services cannot read the `env` context, so the password is written twice; the two must agree.
    assert parts["user"] == env["POSTGRES_USER"]
    assert parts["password"] == env["POSTGRES_PASSWORD"]
    assert parts["dbname"] == env.get("POSTGRES_DB", env["POSTGRES_USER"])
    assert parts["host"] in ("localhost", "127.0.0.1")
    published = [str(p).split(":") for p in postgres["ports"]]
    assert [parts["port"], "5432"] in published, (parts, postgres["ports"])


def test_the_password_is_a_throwaway_not_a_secret(shard, postgres):
    """The container lives as long as the job. A `secrets.` reference would also be empty on a fork
    PR, where the BD tests would then fail for the wrong reason."""
    assert "secrets." not in str(postgres) and "secrets." not in str(_test_url(shard))


def test_the_url_reaches_only_the_jobs_that_run_tests(wf):
    """Set where the suite runs and nowhere else: the audit, fingerprint and gate jobs never see it."""
    assert "BD_TEST_DATABASE_URL" not in str(wf.get("env", {}))
    for name, job in wf["jobs"].items():
        if name not in ("shard", "browser"):
            assert "BD_TEST_DATABASE_URL" not in str(job), name
