"""Every setting the BD CRM reads, typed, in one place (backend/.env.example lists them under "BD CRM").

    from bd import config
    config.BD_DATABASE_URL, config.BD_ADMIN_EMAILS (a frozenset) ...

EVERY NAME STARTS WITH BD_. BD runs inside the proposal tool's process, so a BD setting must never
be mistaken for one of the tool's. BD never reads the tool's own SUPER_ADMIN_EMAIL, ADMIN_EMAILS,
DATABASE_URL or any other unprefixed name; tests/test_bd_config.py scans the package for that.
The one read-only exception is the email domain the tool's sign-in lets in (AUTH_ALLOWED_DOMAIN, as
supabase_client.ALLOWED_DOMAIN), which BD's People table adds logins on (#809): bd/auth.py's
sign_in_domain reads it, and no other BD module imports supabase_client (test_bd_config.py).

NO .env LOADING HERE. python-dotenv is not a BD dependency: the values come from the process
environment, which the container (and the tool's own start-up) fills.

Values are read ONCE, at import. reload() reads them again (a test that changes a variable calls
it through monkeypatch, then again afterwards). The two business-clock overrides are the exception
and are read LIVE on every call, because the test fixture that moves "today" must take effect at
once:

  BD_TODAY  a "YYYY-MM-DD" that replaces today's Central date everywhere (tests). Unset in staging
            and production. bizdate.today_central() is the only reader.
  BD_NOW    a full ISO timestamp that replaces "now" (tests that need a fixed time of day).

The defaults (#805, #806):
  BD_ENABLED                  off     the switch. Off: every /api/bd/ route answers 503 "not turned
                                      on" before it touches the database. Staging sets it on
  BD_DATABASE_URL             unset   BD's Postgres login (bd_app). Unset: every BD route answers 503
  BD_DB_POOL_MIN / _MAX       1 / 5   the connection pool's sizes
  BD_WEEKLY_ENABLED           off     the Friday batch
  BD_WEEKLY_HOUR              16      hour (0-23, Central) from which the Friday batch may run,
                                      when BD's own settings hold no hour
  BD_SUPER_ADMIN_EMAIL        empty   BD's sign-in bootstrap: the one super admin
  BD_ADMIN_EMAILS             empty   BD's sign-in bootstrap: comma-separated admins
  BD_TELEPHONY_PROVIDER       unset   read only by the telephony status panel
  BD_QUO_API_KEY              unset   (the same)
  BD_QUO_WEBHOOK_SECRET       unset   (the same)
  BD_TEST_DATABASE_URL        unset   tests only: an ADMIN url the tests create their databases on
"""
from __future__ import annotations

import os


def _str(name: str, default: str = "") -> str:
    v = os.environ.get(name)
    return default if v is None else v.strip()


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None or not v.strip():
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    v = os.environ.get(name)
    try:
        n = int(str(v).strip()) if v is not None and str(v).strip() else default
    except ValueError:
        n = default
    if lo is not None and n < lo:
        n = default
    if hi is not None and n > hi:
        n = default
    return n


def _emails(name: str) -> frozenset:
    return frozenset(e.strip().lower() for e in _str(name).split(",") if e.strip())


def reload() -> None:
    """(Re)read every setting into this module's globals."""
    g = globals()
    # ── the switch ──
    g["BD_ENABLED"] = _bool("BD_ENABLED", False)
    # ── database ──
    g["BD_DATABASE_URL"] = _str("BD_DATABASE_URL")
    g["BD_DB_POOL_MIN"] = _int("BD_DB_POOL_MIN", 1, lo=0)
    g["BD_DB_POOL_MAX"] = _int("BD_DB_POOL_MAX", 5, lo=1)
    g["BD_TEST_DATABASE_URL"] = _str("BD_TEST_DATABASE_URL")
    # ── BD roles from the environment (sign-in bootstrap) ──
    g["BD_SUPER_ADMIN_EMAIL"] = _str("BD_SUPER_ADMIN_EMAIL").lower()
    g["BD_ADMIN_EMAILS"] = _emails("BD_ADMIN_EMAILS")
    # ── phone / texts (the telephony status panel) ──
    g["BD_TELEPHONY_PROVIDER"] = _str("BD_TELEPHONY_PROVIDER").lower()
    g["BD_QUO_API_KEY"] = _str("BD_QUO_API_KEY")
    g["BD_QUO_WEBHOOK_SECRET"] = _str("BD_QUO_WEBHOOK_SECRET")
    # ── the Friday batch ──
    g["BD_WEEKLY_ENABLED"] = _bool("BD_WEEKLY_ENABLED", False)
    g["BD_WEEKLY_HOUR"] = _int("BD_WEEKLY_HOUR", 16, lo=0, hi=23)


# Declared for readers and linters; reload() below fills them in.
BD_ENABLED: bool
BD_DATABASE_URL: str
BD_DB_POOL_MIN: int
BD_DB_POOL_MAX: int
BD_TEST_DATABASE_URL: str
BD_SUPER_ADMIN_EMAIL: str
BD_ADMIN_EMAILS: frozenset
BD_TELEPHONY_PROVIDER: str
BD_QUO_API_KEY: str
BD_QUO_WEBHOOK_SECRET: str
BD_WEEKLY_ENABLED: bool
BD_WEEKLY_HOUR: int

reload()


# ── the business-clock overrides (read live) ─────────────────────────────────────────────────
def bd_today_override() -> str:
    """The BD_TODAY override as typed ("" when unset). Read on every call."""
    return (os.environ.get("BD_TODAY") or "").strip()


def bd_now_override() -> str:
    """The BD_NOW override as typed ("" when unset). Read on every call."""
    return (os.environ.get("BD_NOW") or "").strip()
