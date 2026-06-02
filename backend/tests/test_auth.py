"""Supabase JWT verification + the API auth gate.

verify_token is tested directly (HS256 path, minting tokens with a test secret).
The gate is tested by restoring the real verifier so an unauthenticated /api/*
call is rejected. Real Google sign-in / asymmetric JWKS is verified live."""
import time

import jwt
import pytest
from fastapi.testclient import TestClient

import main
import supabase_client

SECRET = "test-jwt-secret"
client = TestClient(main.app)


def _token(email, exp_offset=3600, secret=SECRET):
    return jwt.encode(
        {"email": email, "aud": "authenticated", "exp": int(time.time()) + exp_offset},
        secret, algorithm="HS256",
    )


@pytest.fixture(autouse=True)
def _hs256_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(supabase_client, "ALLOWED_DOMAIN", "wetreadwell.com")


# ── verify_token (real logic) ─────────────────────────────────────────
def test_valid_token_returns_lowercased_email(real_verify_token):
    assert real_verify_token("Bearer " + _token("Kyle@WeTreadwell.com")) == "kyle@wetreadwell.com"


def test_wrong_domain_rejected_403(real_verify_token):
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token("Bearer " + _token("kyle@gmail.com"))
    assert e.value.status == 403


def test_bad_signature_rejected_401(real_verify_token):
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token("Bearer " + _token("kyle@wetreadwell.com", secret="wrong-secret"))
    assert e.value.status == 401


def test_expired_token_rejected_401(real_verify_token):
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token("Bearer " + _token("kyle@wetreadwell.com", exp_offset=-30))
    assert e.value.status == 401


def test_missing_header_rejected_401(real_verify_token):
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token(None)
    assert e.value.status == 401


def test_token_without_email_rejected_401(real_verify_token):
    tok = jwt.encode({"aud": "authenticated", "exp": int(time.time()) + 3600},
                     SECRET, algorithm="HS256")
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token("Bearer " + tok)
    assert e.value.status == 401


# ── the API gate (middleware) ─────────────────────────────────────────
def test_api_requires_auth(real_verify_token, monkeypatch):
    # restore the genuine verifier so the gate actually rejects
    monkeypatch.setattr(supabase_client, "verify_token", real_verify_token)
    r = client.post("/api/price", json={"systems": []})  # no Authorization header
    assert r.status_code == 401
    assert r.json()["ok"] is False


def test_public_endpoints_open(real_verify_token, monkeypatch):
    monkeypatch.setattr(supabase_client, "verify_token", real_verify_token)
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/public-config").status_code == 200  # no token needed


def test_valid_token_passes_gate(real_verify_token, monkeypatch):
    monkeypatch.setattr(supabase_client, "verify_token", real_verify_token)
    headers = {"Authorization": "Bearer " + _token("kyle@wetreadwell.com")}
    r = client.post("/api/price", json={"systems": []}, headers=headers)
    assert r.status_code == 200  # authenticated → handler runs
