"""The browser suites' fake sign-in cannot be turned on in staging or prod (#806, Q28).

The BD browser suites sign in with a stand-in: tests/_bd_e2e_server.py replaces the tool's verify
step in the server process the test starts, and tests/_bd_browser.py stands in for the Supabase script
inside the test's own browser context. Neither is a setting. This file proves it from outside:

  * the real app, given EVERY environment variable the browser suites' server gets, still refuses
    the stand-in's token (so the fake lives in that file's code and nowhere in the app's settings);
  * nothing outside backend/tests/ installs or names the stand-in, and the app reads no environment
    variable named for a fake, a bypass or a mock;
  * the server file refuses to start against anything but a test database on this machine, so run
    inside the staging or prod container it exits before the app is even imported;
  * the image and both compose files start main:app and nothing else.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

import _bd_browser
import _bd_e2e_server

BACKEND = pathlib.Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
TESTS = BACKEND / "tests"

SECRET = "not-a-real-password-0177"
STAGING_BD_URL = "postgresql://bd_app:%s@db:5432/treadwell" % SECRET          # staging compose's shape
LOCAL_TEST_URL = "postgresql://bd_test_app:%s@127.0.0.1:5439/bd_test_main_0123456789" % SECRET
TOKEN = "Bearer test:frankie.oduya@example.com"


def _app_sources():
    """The app's own Python: backend/ without the tests and any virtualenv."""
    for p in BACKEND.rglob("*.py"):
        rel = p.relative_to(BACKEND).parts
        if rel[0] in ("tests",) or any(part.startswith((".venv", "venv")) or part == "__pycache__"
                                       for part in rel):
            continue
        yield p


def _shipped_files():
    """Everything the image or a deploy carries that is not a test: app Python, the frontend, the
    Dockerfile, the compose files and the deploy workflow."""
    yield from _app_sources()
    for p in (ROOT / "frontend").rglob("*"):
        if p.suffix in (".js", ".html", ".css") and p.is_file():
            yield p
    for name in ("Dockerfile", "docker-compose.yml", "docker-compose.staging.yml",
                 ".github/workflows/deploy.yml"):
        if (ROOT / name).exists():
            yield ROOT / name


# ── the real app, with every setting the browser server gets ────────────────────────────────────
@pytest.mark.parametrize("path", ["/api/bd/me", "/api/me"])
def test_the_real_app_refuses_the_test_token_with_every_setting_the_browser_server_gets(
        monkeypatch, tmp_path, real_verify_identity, path):
    import supabase_client
    from bd import config as bd_config
    from fastapi.testclient import TestClient

    import main

    for k, v in _bd_browser.server_env(LOCAL_TEST_URL, str(tmp_path)).items():
        monkeypatch.setenv(k, v)
    # The real verifier's HS256 fallback, so a refusal needs no network.
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "e2e-test-secret-not-real")
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    # Put the REAL verify step back (the suite's autouse bypass replaced it).
    monkeypatch.setattr(supabase_client, "verify_identity", real_verify_identity)
    monkeypatch.setattr(supabase_client, "verify_token",
                        lambda authorization: supabase_client.verify_token_claims(authorization)["email"])
    client = TestClient(main.app, raise_server_exceptions=False)
    r = client.get(path, headers={"Authorization": TOKEN})
    assert r.status_code == 401, (r.status_code, r.text)
    assert "frankie" not in r.text


def test_the_browser_server_env_is_the_short_list_it_claims(tmp_path):
    """Nothing from the developer's shell rides along beyond what the OS and Python need."""
    env = _bd_browser.server_env(LOCAL_TEST_URL, str(tmp_path))
    allowed = set(_bd_browser._PASS_THROUGH) | {
        "BD_ENABLED", "BD_DATABASE_URL", "BD_TODAY", "AUTH_ALLOWED_DOMAIN", "SUPABASE_URL",
        "SUPABASE_ANON_KEY", "DRAFTS_DB_PATH", "DIGEST_ENABLED", "PVA_REFRESH_ENABLED",
        "LEADS_AUTOPILOT", "PYTHONUNBUFFERED"}
    assert set(env) <= allowed, sorted(set(env) - allowed)
    assert env["SUPABASE_URL"].endswith(".invalid")
    assert "SUPABASE_SERVICE_ROLE_KEY" not in env and "SUPABASE_DATA_URL" not in env


# ── nothing shipped installs or names the stand-in ──────────────────────────────────────────────
FAKE_NAMES = ("_bd_e2e_server", "_bd_browser", "fake_verify_identity", "fake_claims",
              _bd_browser.SIGNED_IN_KEY)
VERIFY_REPLACED = re.compile(r"supabase_client\s*\.\s*(verify_identity|verify_token_claims|verify_token)\s*=(?!=)")


# A dev script that predates #806 and signs itself in to call the app IN ITS OWN PROCESS through a
# TestClient (it renders proposal documents and exits). It serves nothing, so it is no way in.
IN_PROCESS_ONLY = {"backend/ops/terms_render_proof.py"}


def test_nothing_outside_the_tests_installs_or_names_the_fake_sign_in():
    checked = 0
    for p in _shipped_files():
        rel = p.relative_to(ROOT).as_posix()
        text = p.read_text(encoding="utf-8", errors="replace")
        checked += 1
        for name in FAKE_NAMES:
            assert name not in text, "%s names %s" % (rel, name)
        if rel in IN_PROCESS_ONLY:
            assert "TestClient" in text and "uvicorn" not in text, rel
            continue
        assert not VERIFY_REPLACED.search(text), "%s replaces the verify step" % rel
        assert "setattr(supabase_client" not in text, rel
    assert checked > 100, "vacuity: the scan found almost nothing to read"


ENV_READ = re.compile(r"""(?:environ\.get|environ\[|getenv|_str|_bool|_int|_emails)\(?\s*["']([A-Z][A-Z0-9_]*)["']""")
SUSPECT = re.compile(r"E2E|FAKE|BYPASS|MOCK|STUB|SKIP_AUTH|NO_AUTH|SIGN_?IN|TEST_TOKEN|DEV_LOGIN")


def test_the_app_reads_no_setting_named_for_a_fake_or_a_bypass():
    names = set()
    for p in _app_sources():
        names |= set(ENV_READ.findall(p.read_text(encoding="utf-8", errors="replace")))
    assert {"BD_ENABLED", "SUPABASE_URL", "AUTH_ALLOWED_DOMAIN"} <= names, "vacuity: the regex reads nothing"
    assert not sorted(n for n in names if SUSPECT.search(n))


# ── the server file refuses anything but a local test database ──────────────────────────────────
@pytest.mark.parametrize("url", [
    "",
    STAGING_BD_URL,
    "postgresql://postgres.abcd:%s@aws-0-us-east-1.pooler.supabase.com:5432/postgres" % SECRET,
    "postgresql://bd_app:%s@127.0.0.1:5432/treadwell" % SECRET,         # local, but not a test database
    "postgresql://bd_test_app:%s@db.example.com:5432/bd_test_x" % SECRET,  # a test name, far away
])
def test_the_browser_server_refuses_any_database_but_a_local_test_one(url):
    assert _bd_e2e_server.refusal(url)


def test_the_browser_server_takes_a_local_test_database_on_127_0_0_1_only():
    assert _bd_e2e_server.refusal(LOCAL_TEST_URL) == ""
    assert _bd_e2e_server.refusal(LOCAL_TEST_URL, host="0.0.0.0")
    assert _bd_e2e_server.HOST == "127.0.0.1"


def test_run_against_stagings_database_it_exits_before_the_app_loads(tmp_path):
    roles = tmp_path / "roles.json"
    roles.write_text(json.dumps({}), encoding="utf-8")
    env = dict(os.environ, BD_DATABASE_URL=STAGING_BD_URL, BD_ENABLED="on")
    proc = subprocess.run([sys.executable, str(TESTS / "_bd_e2e_server.py"), "8999", str(roles)],
                          cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=60)
    assert proc.returncode == 2, (proc.returncode, proc.stderr[-2000:])
    assert proc.stderr.startswith("refused: "), proc.stderr[-2000:]
    assert "[main]" not in proc.stdout, "main.py was imported"
    assert SECRET not in proc.stderr and "db:5432" not in proc.stderr


# ── the image and the compose files start the app, nothing else ─────────────────────────────────
def test_the_image_and_both_compose_files_start_main_app_only():
    cmd = [ln for ln in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines()
           if ln.startswith("CMD ")]
    assert len(cmd) == 1 and json.loads(cmd[0][4:])[:2] == ["uvicorn", "main:app"], cmd
    import yaml

    for name, service in (("docker-compose.yml", "proposal-tool"), ("docker-compose.staging.yml", "app")):
        app = yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))["services"][service]
        assert "command" not in app and "entrypoint" not in app, name
