"""Shared test setup. Makes the backend importable, and bypasses the Supabase
auth gate for tests that aren't about auth (so /api/* calls don't 401)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
import supabase_client

# Capture the REAL verifier BEFORE any test patches it (test_auth uses this to
# exercise the genuine logic, while everything else runs with the bypass below).
_REAL_VERIFY_TOKEN = supabase_client.verify_token


@pytest.fixture(autouse=True)
def _bypass_auth(monkeypatch):
    """Authenticate every request as a fixed @wetreadwell.com user so the API
    gate doesn't 401 in tests that aren't exercising auth."""
    monkeypatch.setattr(supabase_client, "verify_token",
                        lambda authorization: "tester@wetreadwell.com")


@pytest.fixture
def real_verify_token():
    """The genuine verify_token (un-bypassed) for the auth tests."""
    return _REAL_VERIFY_TOKEN
