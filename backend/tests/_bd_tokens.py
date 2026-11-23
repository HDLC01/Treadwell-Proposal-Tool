"""Token helpers for the BD tests that run the proposal tool's REAL verifier (#806).

BD's own token check is not carried over: BD trusts the tool's auth gate, which verifies with
supabase_client.verify_token_claims. So these helpers (BD's tests/_tokens.py, ported) aim at that
verifier. Nothing here touches the network or writes key material down: the keys are generated
when this module is imported.

    from _bd_tokens import claims, rs256, es256, hs256, DROP, configure_project

    @pytest.fixture(autouse=True)
    def project(monkeypatch):
        configure_project(monkeypatch)        # env + the JWKS lookup (kid "rsa" / "ec")

configure_project points the tool at a made-up Supabase project (SUPABASE_URL, the HS256 secret),
makes example.com the allowed domain (so every person here is made up), and replaces
supabase_client._jwk_client (the one thing that would reach Supabase) with a lookup by `kid` over
the two test public keys; every other line of the verifier runs for real. configure_real_jwks
instead keeps the REAL PyJWKClient and replaces only the HTTP fetch of the key set.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

import supabase_client

PROJECT = "https://bdtest.supabase.co"
ISS = PROJECT + "/auth/v1"
DOMAIN = "example.com"
# Generated per run: no key material is written down anywhere.
HS_SECRET = secrets.token_urlsafe(32)
WRONG_HS = secrets.token_urlsafe(32)

RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EC_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_EC = ec.generate_private_key(ec.SECP256R1())

DROP = object()                      # claims(x=DROP) leaves claim x out

_REAL_JWK_CLIENT = supabase_client._jwk_client      # captured at import, before any test replaces it


# ── the project the tests pretend to be ──────────────────────────────────────────────────────
class _Key:
    def __init__(self, key):
        self.key = key


class FakeJwks:
    """Stand-in for the tool's PyJWKClient: the public key for the token's `kid` ("rsa" or "ec")."""

    def get_signing_key_from_jwt(self, token):
        kid = jwt.get_unverified_header(token).get("kid")
        if kid == "rsa":
            return _Key(RSA_KEY.public_key())
        if kid == "ec":
            return _Key(EC_KEY.public_key())
        raise jwt.PyJWKClientError("no such key")


def configure_project(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", PROJECT)
    monkeypatch.setenv("SUPABASE_JWT_SECRET", HS_SECRET)
    monkeypatch.setattr(supabase_client, "ALLOWED_DOMAIN", DOMAIN)
    monkeypatch.setattr(supabase_client, "ALLOWED_PROVIDERS", frozenset({"google"}))
    jwks = FakeJwks()
    monkeypatch.setattr(supabase_client, "_jwk_client", lambda: jwks)


def jwks_document(kid="rsa"):
    """The key set Supabase would serve at /auth/v1/.well-known/jwks.json for the RSA test key."""
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(RSA_KEY.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return {"keys": [jwk]}


class JwksTraffic:
    """What the real PyJWKClient did while a test ran: how many times it asked for the key set
    over the (replaced) HTTP, and every URL anything tried to open."""

    def __init__(self):
        self.fetches = 0
        self.urls = []


def configure_real_jwks(monkeypatch, kid="rsa"):
    """Keep supabase_client._jwk_client and PyJWKClient REAL; replace only the network. Returns
    JwksTraffic. The client cache is cleared before and after, so no test sees another's keys."""
    import urllib.request

    traffic = JwksTraffic()
    document = jwks_document(kid)

    def fetch_data(self):
        traffic.fetches += 1
        return document

    def urlopen(req, *a, **kw):
        traffic.urls.append(getattr(req, "full_url", str(req)))
        raise OSError("the tests have no network")

    _REAL_JWK_CLIENT.cache_clear()
    monkeypatch.setattr(supabase_client, "_jwk_client", _REAL_JWK_CLIENT)
    monkeypatch.setattr(jwt.PyJWKClient, "fetch_data", fetch_data)
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setenv("SUPABASE_URL", PROJECT)
    return traffic


def clear_jwks_cache():
    _REAL_JWK_CLIENT.cache_clear()


# ── claims and tokens ────────────────────────────────────────────────────────────────────────
def claims(**over):
    now = int(time.time())
    c = {
        "iss": ISS,
        "aud": "authenticated",
        "sub": "0b7c2c5e-1111-4a2b-9c3d-123456789abc",
        "email": "avery.quill@example.com",
        "exp": now + 3600,
        "iat": now,
        "role": "authenticated",
        "app_metadata": {"provider": "google", "providers": ["google"]},
        "user_metadata": {"full_name": "Avery Quill"},
        "amr": [{"method": "oauth", "timestamp": now}],
        "is_anonymous": False,
    }
    for k, v in over.items():
        if v is DROP:
            c.pop(k, None)
        else:
            c[k] = v
    return c


def rs256(c, key=RSA_KEY, kid="rsa"):
    return "Bearer " + jwt.encode(c, key, algorithm="RS256", headers={"kid": kid})


def es256(c, key=EC_KEY, kid="ec"):
    return "Bearer " + jwt.encode(c, key, algorithm="ES256", headers={"kid": kid})


def hs256(c, signing=None):
    return "Bearer " + jwt.encode(c, signing or HS_SECRET, algorithm="HS256")


def none_alg(c):
    return "Bearer " + jwt.encode(c, None, algorithm="none")


# ── tokens built by hand (the library refuses to make the hostile ones) ──────────────────────
def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def public_pem(key=RSA_KEY) -> bytes:
    return key.public_key().public_bytes(serialization.Encoding.PEM,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)


def forge(header: dict, payload: dict, sign_with=None, raw_signature: bytes = b"") -> str:
    """"Bearer <header>.<payload>.<signature>" with the header exactly as given (so any `alg`,
    `kid`, `jku`, `x5u`, `jwk`, `crit` ...). `sign_with` = (PyJWT algorithm name, key) signs the
    input with that algorithm whatever the header says; otherwise `raw_signature` is used."""
    head = b64(json.dumps(header).encode())
    body = b64(json.dumps(payload).encode())
    signing_input = (head + "." + body).encode("ascii")
    if sign_with is not None:
        name, key = sign_with
        raw_signature = jwt.algorithms.get_default_algorithms()[name].sign(signing_input, key)
    return "Bearer " + head + "." + body + "." + b64(raw_signature)


def hs256_with_public_key_as_secret(c, key=RSA_KEY, kid="rsa") -> str:
    """The classic RS256 -> HS256 confusion: an HS256 token whose HMAC key is the RSA PUBLIC KEY's
    PEM. Built by hand: PyJWT refuses to HMAC with a PEM."""
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT", "kid": kid}).encode())
    body = b64(json.dumps(c).encode())
    sig = b64(hmac.new(public_pem(key), (head + "." + body).encode(), hashlib.sha256).digest())
    return "Bearer " + head + "." + body + "." + sig


def segments(authorization: str):
    """The three base64 parts of a "Bearer a.b.c" value (for 'the token is never echoed' checks)."""
    return authorization.split(" ", 1)[1].split(".")
