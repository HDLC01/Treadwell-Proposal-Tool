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
PROJECT = "https://testproject.supabase.co"
client = TestClient(main.app)

# What a real staff session carries (read off a live Google sign-in on staging, 2026-09-28):
# issued by our project, provider google in app_metadata, an "oauth" sign-in method.
GOOGLE = {"iss": PROJECT + "/auth/v1", "app_metadata": {"provider": "google", "providers": ["google"]},
          "amr": [{"method": "oauth", "timestamp": 1784842732}], "is_anonymous": False}


def _token(email, exp_offset=3600, secret=SECRET, **claims):
    body = {"email": email, "aud": "authenticated", "exp": int(time.time()) + exp_offset}
    body.update(GOOGLE)
    body.update(claims)
    return jwt.encode({k: v for k, v in body.items() if v is not None}, secret, algorithm="HS256")


@pytest.fixture(autouse=True)
def _hs256_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setenv("SUPABASE_URL", PROJECT)
    monkeypatch.setattr(supabase_client, "ALLOWED_DOMAIN", "wetreadwell.com")
    monkeypatch.setattr(supabase_client, "ALLOWED_PROVIDERS", frozenset({"google"}))
    # The JWKS path is tried first and would go to the network for this made-up project.
    monkeypatch.setattr(supabase_client, "_jwk_client", _no_jwks)


def _no_jwks():
    raise RuntimeError("no JWKS in tests")


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
    tok = jwt.encode(dict(GOOGLE, aud="authenticated", exp=int(time.time()) + 3600),
                     SECRET, algorithm="HS256")
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token("Bearer " + tok)
    assert e.value.status == 401


def test_a_token_with_no_expiry_is_rejected_401(real_verify_token):
    """PyJWT checks `exp` only when it is there, so a signed token without one would never expire
    (#806: the BD CRM now relies on this verifier, and BD's own required it). Supabase always sets it.

    Mutation: drop options={"require": ["exp"]} -- the token gets in."""
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token("Bearer " + _token("kyle@wetreadwell.com", exp=None))
    assert e.value.status == 401 and e.value.detail == "Invalid or expired token."


@pytest.mark.parametrize("why, email", [
    ("the Kelvin sign, which lower-cases to k", chr(0x212A) + "yle@wetreadwell.com"),
    ("a Cyrillic a in the name", "kyle" + chr(0x0430) + "@wetreadwell.com"),
    ("a NUL", "ky" + chr(0) + "le@wetreadwell.com"),
    ("two @", "kyle@evil.example@wetreadwell.com"),
])
def test_an_email_that_is_not_plain_ascii_with_one_at_is_rejected_403(real_verify_token, why, email):
    """#806: an address that is not plain printable ASCII with one "@" could lower-case into someone
    else's ("K" + "yle" with the Kelvin sign is kyle) or not be storable. Refused like a wrong domain."""
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token("Bearer " + _token(email))
    assert e.value.status == 403, why


@pytest.mark.parametrize("value", [5, True, ["kyle@wetreadwell.com"], {"a": "kyle@wetreadwell.com"}])
def test_an_email_claim_of_the_wrong_type_is_401_not_a_crash(real_verify_token, value):
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token("Bearer " + _token(value))
    assert e.value.status == 401


def test_verify_identity_returns_the_email_the_subject_and_the_name(real_verify_identity):
    """The gate's verify step keeps who signed in, not just the address (#806)."""
    tok = _token("Kyle@WeTreadwell.com", sub="7c1e0f5a-0000-4000-8000-000000000001",
                 user_metadata={"full_name": "  Kyle Example  "})
    assert real_verify_identity("Bearer " + tok) == {
        "email": "kyle@wetreadwell.com", "sub": "7c1e0f5a-0000-4000-8000-000000000001", "name": "Kyle Example"}
    bare = _token("kyle@wetreadwell.com")
    assert real_verify_identity("Bearer " + bare) == {"email": "kyle@wetreadwell.com", "sub": None, "name": None}


# ── only a Google sign-in from our own project is staff (security audit, 2026-09-28) ─────────────
@pytest.mark.parametrize("why, claims, status", [
    ("an email/password account", {"app_metadata": {"provider": "email", "providers": ["email"]},
                                   "amr": [{"method": "password", "timestamp": 1}]}, 403),
    ("a magic-link account", {"app_metadata": {"provider": "email", "providers": ["email"]},
                              "amr": [{"method": "otp", "timestamp": 1}]}, 403),
    ("no provider at all", {"app_metadata": None, "amr": None}, 403),
    ("a Google identity, but this session signed in with a password",
     {"app_metadata": {"provider": "email", "providers": ["email", "google"]},
      "amr": [{"method": "password", "timestamp": 1}]}, 403),
    ("an anonymous session", {"is_anonymous": True}, 403),
    ("another Supabase project", {"iss": "https://someoneelse.supabase.co/auth/v1"}, 401),
    ("no issuer", {"iss": None}, 401),
    ("provider only in user_metadata (the user can edit that)",
     {"app_metadata": {"provider": "email", "providers": ["email"]}, "amr": None,
      "user_metadata": {"provider": "google", "email_verified": True}}, 403),
])
def test_only_a_google_session_from_our_project_gets_in(real_verify_token, why, claims, status):
    """A @wetreadwell.com address with a good signature used to be enough. The shared Supabase
    project also issues tokens to email/password and magic-link accounts (its email sign-up was on),
    so an address on our domain was the only thing standing between a stranger and the staff tool.

    Mutation: drop the provider check -- every 403 row gets in."""
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token("Bearer " + _token("kyle@wetreadwell.com", **claims))
    assert e.value.status == status, why


def test_a_real_google_session_still_gets_in(real_verify_token):
    """The shape a live staff sign-in carries, and the same with no `amr` at all (an older token)."""
    assert real_verify_token("Bearer " + _token("hanz@wetreadwell.com")) == "hanz@wetreadwell.com"
    assert real_verify_token("Bearer " + _token("hanz@wetreadwell.com", amr=None)) == "hanz@wetreadwell.com"


def test_a_rejected_token_says_nothing_about_why(real_verify_token):
    """The library's reason ("Signature verification failed", a key id...) goes to the server log,
    not to whoever sent the token."""
    with pytest.raises(supabase_client.AuthError) as e:
        real_verify_token("Bearer " + _token("kyle@wetreadwell.com", secret="wrong-secret"))
    assert e.value.detail == "Invalid or expired token."


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


def test_an_email_password_session_is_stopped_at_the_gate(real_verify_token, monkeypatch):
    """The same refusal through the real middleware, on a data route."""
    monkeypatch.setattr(supabase_client, "verify_token", real_verify_token)
    tok = _token("kyle@wetreadwell.com", app_metadata={"provider": "email", "providers": ["email"]},
                 amr=[{"method": "password", "timestamp": 1}])
    r = client.post("/api/price", json={"systems": []}, headers={"Authorization": "Bearer " + tok})
    assert r.status_code == 403 and r.json()["ok"] is False


@pytest.mark.parametrize("status", ["paused", "banned"])
def test_a_paused_or_banned_account_is_stopped_on_its_next_request(monkeypatch, status):
    """Pausing someone on the Admin page used to change a label: their open session kept working.
    Now the gate reads the profile's status on every request. /api/me still answers, so the page can
    say who is signed in.

    Mutation: drop the status check in _nav_gate -- the paused caller gets 200."""
    import profiles
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda email: {"id": "u1", "email": email, "role": "user", "status": status})
    r = client.post("/api/price", json={"systems": []}, headers={"Authorization": "Bearer x"})
    assert r.status_code == 403 and r.json().get("account_paused") is True
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda email: {"id": "u1", "email": email, "role": "user", "status": "active"})
    main._profile_cache_clear()
    assert client.post("/api/price", json={"systems": []},
                       headers={"Authorization": "Bearer x"}).status_code == 200
