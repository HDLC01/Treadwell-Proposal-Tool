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
