"""Shared test setup. Makes the backend importable, and bypasses the Supabase
auth gate for tests that aren't about auth (so /api/* calls don't 401)."""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import pytest
import supabase_client

# Capture the REAL verifier BEFORE any test patches it (test_auth uses this to
# exercise the genuine logic, while everything else runs with the bypass below).
_REAL_VERIFY_TOKEN = supabase_client.verify_token


# ── Never let the suite write to the production data store ────────────────────
#
# `backend/.env` sets SUPABASE_URL to the live cloud project, and `data_url()` falls back to
# it when SUPABASE_DATA_URL is unset. `main` loads that .env on import — so simply running
# pytest locally pointed every draft/event write at PRODUCTION. Measured on 2026-08-05: a
# single afternoon of local runs left 637 fake `generated`/`created`/`marked_test` rows in the
# prod events table, which is what the History page reads. Fixtures create and delete real
# `drafts` rows there too.
#
# Nothing announced this. The tests passed either way, which is exactly why it went unnoticed.
#
# CI is unaffected (no credentials, so `get_client()` raises and store-backed tests are the
# ones that fail loudly). This guard makes the local behaviour match that: fail fast with an
# explanation instead of quietly polluting a live audit log.
#
# To run store-backed tests deliberately, point them somewhere safe:
#   SUPABASE_DATA_URL=<staging PostgREST>   (staging keeps its data on the VPS)
# or acknowledge the risk for one run:
#   TW_ALLOW_PROD_DATA_WRITES=1
_PROD_DATA_HOSTS = ("hyjowrzgrrxrbfbaxkyu.supabase.co",)


def _resolved_data_host() -> str:
    """The host the DATA store WILL resolve to once the app is imported.

    The check has to load `backend/.env` itself. `main` is what normally loads it, and `main`
    is imported during collection — long after pytest_configure. The first version of this
    guard read `data_url()` straight away, got an empty string, decided everything was fine,
    and let the run write to production anyway. It reported nothing and looked like it worked.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv(pathlib.Path(__file__).resolve().parent.parent / ".env", override=True)
    except ImportError:
        pass
    try:
        url = supabase_client.data_url() or ""
    except Exception:                       # noqa: BLE001 — unconfigured is the safe case
        return ""
    return url.split("//", 1)[-1].split("/", 1)[0].lower()


# Every module that talks to the store binds the factory by name at import time
# (`from supabase_client import get_client`), so each binding has to be closed off separately —
# patching only `supabase_client.get_client` would leave drafts.py holding the original.
_CLIENT_HOLDERS = ("supabase_client", "drafts", "calendar_events", "leads", "profiles")


@pytest.fixture(autouse=True)
def _no_prod_data_writes(monkeypatch):
    """Make the REAL data client unreachable when it points at production.

    Deliberately not a session-level refusal: most of the suite never touches the store, and
    the store-backed tests are supposed to run against the in-memory fake (they monkeypatch
    `get_client` themselves, which takes precedence over this). What this stops is the case
    that actually happened — a test reaching the live client by default and writing to prod.

    A test that genuinely needs a real store can set TW_ALLOW_PROD_DATA_WRITES=1.
    """
    if os.environ.get("TW_ALLOW_PROD_DATA_WRITES") == "1":
        return
    if _resolved_data_host() not in _PROD_DATA_HOSTS:
        return

    def _refuse():
        raise RuntimeError(
            "This test reached the REAL data client, which resolves to the PRODUCTION Supabase "
            "project. Writing there creates and deletes real `drafts` rows and leaves fake "
            "`events` on the History page.\n"
            "Use the `fake_supabase` fixture (see test_archive.py) and monkeypatch "
            "<module>.get_client, or set TW_ALLOW_PROD_DATA_WRITES=1 if you really mean it.")

    for name in _CLIENT_HOLDERS:
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "get_client"):
            monkeypatch.setattr(mod, "get_client", _refuse)


@pytest.fixture(autouse=True)
def _bypass_auth(monkeypatch):
    """Authenticate every request as a fixed @wetreadwell.com user so the API
    gate doesn't 401 in tests that aren't exercising auth."""
    monkeypatch.setattr(supabase_client, "verify_token",
                        lambda authorization: "tester@wetreadwell.com")


@pytest.fixture(autouse=True)
def _clear_drafts_cache():
    """drafts.py keeps a module-level TTLCache for the project lists. Clear it
    around every test so a cached list built from one test's fake store can't
    leak into another's."""
    import drafts
    drafts._cache_clear()
    yield
    drafts._cache_clear()


@pytest.fixture
def real_verify_token():
    """The genuine verify_token (un-bypassed) for the auth tests."""
    return _REAL_VERIFY_TOKEN


# ── In-memory Supabase fake ───────────────────────────────────────────
# A tiny stand-in for the supabase-py client so the profiles/admin logic can be
# unit-tested without a network round-trip (local can't reach Supabase anyway).
# Supports the exact chains profiles.py uses: table().select()/insert()/update()/
# delete() with .eq()/.in_()/.order()/.limit()/.or_()/.execute(). Records every
# .or_() filter string in `.captures` so the injection-sanitization test can
# assert what actually reached PostgREST.
class FakeResult:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class FakeTable:
    def __init__(self, store, name, captures):
        self.store, self.name, self.captures = store, name, captures
        self._op = self._payload = None
        self._filters = []
        self._negate_next = False

    def select(self, *a, **k):
        self._op = "select"; return self

    def insert(self, row):
        self._op, self._payload = "insert", row; return self

    def update(self, patch):
        self._op, self._payload = "update", patch; return self

    def delete(self):
        self._op = "delete"; return self

    def eq(self, k, v):
        self._filters.append((k, v)); return self

    def in_(self, k, vals):
        self._filters.append((k, list(vals))); return self

    @property
    def not_(self):
        self._negate_next = True; return self

    def is_(self, k, v):
        # PostgREST IS NULL filter (v == "null"). Records (k, sentinel, negate).
        self._filters.append((k, "__isnull__", self._negate_next))
        self._negate_next = False
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        return self

    def or_(self, expr):
        self.captures.append(expr); return self

    def _match(self, rows):
        sel = list(rows)
        for f in self._filters:
            if len(f) == 3 and f[1] == "__isnull__":
                k, _, neg = f
                sel = [r for r in sel if (r.get(k) is not None) == bool(neg)]
            else:
                k, v = f
                if isinstance(v, list):
                    sel = [r for r in sel if r.get(k) in v]
                else:
                    sel = [r for r in sel if r.get(k) == v]
        return sel

    def execute(self):
        rows = self.store.setdefault(self.name, [])
        if self._op == "insert":
            self.store[self.name].append(dict(self._payload))
            return FakeResult(data=[self._payload])
        if self._op == "update":
            for r in self._match(rows):
                r.update(self._payload)
            return FakeResult(data=self._match(rows))
        if self._op == "delete":
            matched = self._match(rows)
            self.store[self.name] = [r for r in rows if r not in matched]
            return FakeResult(data=matched)  # supabase-py returns the deleted rows
        sel = self._match(rows)
        return FakeResult(data=sel, count=len(sel))


class FakeClient:
    def __init__(self, store=None):
        self.store = store if store is not None else {}
        self.captures = []

    def table(self, name):
        return FakeTable(self.store, name, self.captures)


@pytest.fixture
def fake_supabase():
    """Factory → a FakeClient seeded with the given {table: [rows]} store."""
    def _make(store=None):
        return FakeClient(store)
    return _make
