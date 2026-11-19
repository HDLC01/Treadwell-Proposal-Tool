"""Supabase integration.

Two jobs:
  1. A **service-role** Postgres client for the backend's data access (drafts +
     events). The service-role key bypasses RLS and is NEVER sent to the browser.
  2. **Auth gate** — verify the Supabase Auth (Google) JWT the browser sends on
     each `/api/*` call, and enforce the allowed email domain.

Env:
  SUPABASE_URL                https://<ref>.supabase.co
  SUPABASE_SERVICE_ROLE_KEY   server-side key (bypasses RLS) — keep secret
  SUPABASE_ANON_KEY           publishable key (handed to the frontend)
  SUPABASE_JWT_SECRET         legacy HS256 secret (only if the project signs HS256)
  AUTH_ALLOWED_DOMAIN         email domain allowed to sign in (default wetreadwell.com)
  AUTH_ALLOWED_PROVIDERS      sign-in methods accepted, comma-separated (default google)
"""
from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

log = logging.getLogger("proposal_tool.auth")

ALLOWED_DOMAIN = (
    (os.environ.get("AUTH_ALLOWED_DOMAIN") or "wetreadwell.com").strip().lower().lstrip("@")
)
# Only these Supabase sign-in providers are staff. See verify_token_claims.
ALLOWED_PROVIDERS = frozenset(
    p.strip().lower() for p in (os.environ.get("AUTH_ALLOWED_PROVIDERS") or "google").split(",")
    if p.strip()
)


class AuthError(Exception):
    """Auth/authorization failure. `status` maps to an HTTP status in main.py."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def supabase_url() -> str:
    return (os.environ.get("SUPABASE_URL") or "").rstrip("/")


def anon_key() -> str:
    return os.environ.get("SUPABASE_ANON_KEY") or ""


def is_configured() -> bool:
    """True when the backend can reach Supabase (URL + service-role key set)."""
    return bool(supabase_url() and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"))


def data_url() -> str:
    """Base URL for the DATA store (drafts/events/profiles). Defaults to the
    Supabase project URL, but staging overrides it (SUPABASE_DATA_URL) to point
    at a self-hosted PostgREST in front of a VPS Postgres — so staging's test
    data lives on the VPS while AUTH still verifies against cloud Supabase."""
    return (os.environ.get("SUPABASE_DATA_URL") or supabase_url()).rstrip("/")


def data_key() -> str:
    return os.environ.get("SUPABASE_DATA_KEY") or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""


@lru_cache(maxsize=1)
def get_client():
    """Service-role client for DATA access (drafts/events/profiles tables).
    Points at `data_url()` — cloud Supabase in prod, the VPS PostgREST in staging."""
    from supabase import create_client

    url, key = data_url(), data_key()
    if not (url and key):
        raise AuthError(503, "Data store not configured (SUPABASE_DATA_URL / KEY).")
    return create_client(url, key)


# PostgREST 12's "not in the schema cache" (prod Supabase, and staging's postgrest v12.2.3) and
# Postgres's own undefined_table, which an older PostgREST passes through. One list for every
# caller: PostgREST has changed this code before.
TABLE_MISSING_CODES = ("PGRST205", "42P01")


def table_missing(exc: BaseException) -> bool:
    """True only for "this table does not exist on this database".

    Read off the error's `code`, never its message: a timeout, a 5xx or a dropped connection is a
    database that HAS the table and failed to answer, and has to be treated as a failure, not as a
    migration that has not run."""
    return str(getattr(exc, "code", "") or "") in TABLE_MISSING_CODES


@lru_cache(maxsize=1)
def get_auth_client():
    """Service-role client bound to the cloud Supabase project for AUTH ADMIN
    ops (ban/unban/delete user via GoTrue). Always the real Supabase project,
    even in staging (auth never moves off Supabase)."""
    from supabase import create_client

    url, key = supabase_url(), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        raise AuthError(503, "Supabase auth not configured (SUPABASE_URL / SERVICE_ROLE_KEY).")
    return create_client(url, key)


# ── Auth: verify the Supabase JWT the browser sends ───────────────────
@lru_cache(maxsize=1)
def _jwk_client():
    import jwt
    return jwt.PyJWKClient(f"{supabase_url()}/auth/v1/.well-known/jwks.json")


def verify_token_claims(authorization: Optional[str]) -> dict:
    """Verify a `Authorization: Bearer <jwt>` Supabase token and return its
    validated claims (with `email` lowercased). Supports both HS256 (legacy
    shared secret) and asymmetric (RS/ES via JWKS) signing — PyJWT enforces
    the `exp` claim, so expired tokens are rejected here.

    Raises AuthError(401) if missing/invalid/expired, AuthError(403) if the
    email's domain isn't allowed.

    `exp` is REQUIRED (#806): PyJWT checks it only when present, so a signed token without one
    would never expire. Supabase always sets it.
    """
    import jwt

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError(401, "Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()

    try:
        try:
            key = _jwk_client().get_signing_key_from_jwt(token).key
            payload = jwt.decode(token, key, algorithms=["RS256", "ES256"], audience="authenticated",
                                 options={"require": ["exp"]})
        except Exception:
            secret = os.environ.get("SUPABASE_JWT_SECRET")
            if not secret:
                raise AuthError(503, "SUPABASE_JWT_SECRET not set for HS256 tokens.")
            payload = jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated",
                                 options={"require": ["exp"]})
    except AuthError:
        raise
    except Exception as exc:  # bad signature / expired / malformed
        # The reason stays in the server log; the caller learns only that it failed. %r, never %s:
        # the text of a bad-token error can carry the caller's own `kid`, and a line break in it
        # would forge a log line (CWE-117). repr() escapes every control character.
        log.info("token rejected: %r", exc)
        raise AuthError(401, "Invalid or expired token.")

    # WHO MAY SIGN IN (security audit, 2026-09-28). A good signature and a @wetreadwell.com
    # address are not enough on their own: the shared Supabase project also issues tokens for
    # email/password and magic-link accounts, and its email sign-up was switched on. Staff sign
    # in with Google, so only a Google session counts.
    #   * The token must come from OUR project (`iss`), not merely be signed with a key we trust.
    #   * The provider is read from `app_metadata`, which only Supabase itself can write.
    #     `user_metadata` (where `email_verified` sits) is the user's own to edit, so it is never
    #     trusted here.
    #   * `amr` says how THIS session was signed in. A Google session carries an "oauth" method; an
    #     account that also has a password identity cannot use it to reach the app.
    #   * An anonymous session is never staff.
    project = supabase_url()
    if project and str(payload.get("iss") or "").rstrip("/") != project + "/auth/v1":
        raise AuthError(401, "Invalid or expired token.")
    app_meta = payload.get("app_metadata") if isinstance(payload.get("app_metadata"), dict) else {}
    providers = {str(p).lower() for p in (app_meta.get("providers") or []) if p}
    providers.add(str(app_meta.get("provider") or "").lower())
    amr = payload.get("amr")
    methods = ({str(m.get("method") or "").lower() for m in amr if isinstance(m, dict)}
               if isinstance(amr, list) else None)
    oauth_only = "email" not in ALLOWED_PROVIDERS and "phone" not in ALLOWED_PROVIDERS
    if (payload.get("is_anonymous") is True or not (providers & ALLOWED_PROVIDERS)
            or (oauth_only and methods is not None and "oauth" not in methods)):
        raise AuthError(403, "Sign in with your Treadwell Google account.")

    raw_email = payload.get("email")
    raw_email = raw_email.strip() if isinstance(raw_email, str) else ""
    email = raw_email.lower()
    if not email:
        raise AuthError(401, "Token carries no email.")
    # Plain printable ASCII and one "@" only (#806): str.lower() folds the Kelvin sign to "k", so a
    # look-alike address could otherwise lower-case into a real one, and a NUL cannot be stored.
    plain = raw_email.isascii() and raw_email.isprintable() and email.count("@") == 1
    if not plain or not email.endswith("@" + ALLOWED_DOMAIN):
        raise AuthError(403, f"Access is restricted to @{ALLOWED_DOMAIN} accounts.")
    payload["email"] = email
    return payload


def verify_token(authorization: Optional[str]) -> str:
    """Verify the token and return just the (lowercased) email."""
    return verify_token_claims(authorization)["email"]


def identity_of(claims: dict) -> dict:
    """The verified identity the gate keeps on the request: email, subject id and display name."""
    meta = claims.get("user_metadata") if isinstance(claims.get("user_metadata"), dict) else {}
    name = str(meta.get("full_name") or meta.get("name") or "").strip()
    return {"email": claims["email"], "sub": str(claims.get("sub") or "") or None, "name": name or None}


def verify_identity(authorization: Optional[str]) -> dict:
    """THE AUTH GATE'S VERIFY STEP (#806): verify the token and return its identity
    ({email, sub, name}). main._auth_gate keeps it on the request (request.state.auth_claims) for
    whatever reads more than the email; the BD CRM reads it there. Raises as verify_token_claims."""
    return identity_of(verify_token_claims(authorization))
