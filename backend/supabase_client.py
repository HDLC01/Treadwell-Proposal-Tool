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
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

ALLOWED_DOMAIN = (
    (os.environ.get("AUTH_ALLOWED_DOMAIN") or "wetreadwell.com").strip().lower().lstrip("@")
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


@lru_cache(maxsize=1)
def get_client():
    """Service-role Supabase client (server-side; bypasses RLS). Lazy + cached."""
    from supabase import create_client

    url, key = supabase_url(), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        raise AuthError(503, "Supabase not configured (SUPABASE_URL / SERVICE_ROLE_KEY).")
    return create_client(url, key)


# ── Auth: verify the Supabase JWT the browser sends ───────────────────
@lru_cache(maxsize=1)
def _jwk_client():
    import jwt
    return jwt.PyJWKClient(f"{supabase_url()}/auth/v1/.well-known/jwks.json")


def verify_token(authorization: Optional[str]) -> str:
    """Verify a `Authorization: Bearer <jwt>` Supabase token and return the
    user's email. Supports both HS256 (legacy shared secret) and asymmetric
    (RS/ES via JWKS) signing, so it works regardless of the project's setting.

    Raises AuthError(401) if the token is missing/invalid/expired, or
    AuthError(403) if the email's domain isn't allowed.
    """
    import jwt

    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError(401, "Missing bearer token.")
    token = authorization.split(" ", 1)[1].strip()

    try:
        alg = (jwt.get_unverified_header(token).get("alg") or "").upper()
        if alg.startswith("HS"):
            secret = os.environ.get("SUPABASE_JWT_SECRET")
            if not secret:
                raise AuthError(503, "SUPABASE_JWT_SECRET not set for HS256 tokens.")
            payload = jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
        else:
            key = _jwk_client().get_signing_key_from_jwt(token).key
            payload = jwt.decode(token, key, algorithms=[alg], audience="authenticated")
    except AuthError:
        raise
    except Exception as exc:  # bad signature / expired / malformed
        raise AuthError(401, f"Invalid or expired token: {exc}")

    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise AuthError(401, "Token carries no email.")
    if not email.endswith("@" + ALLOWED_DOMAIN):
        raise AuthError(403, f"Access is restricted to @{ALLOWED_DOMAIN} accounts.")
    return email
