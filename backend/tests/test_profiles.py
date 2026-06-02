"""Profiles + admin guardrails (Supabase-backed, run against an in-memory fake).

Covers the security-relevant logic added with the auth/admin work:
  - ensure_profile: super-admin bootstrap by email, role-preservation, backfill
  - list_users: PostgREST filter-injection sanitization (the CRITICAL audit fix)
  - _can_act / set_role / set_status: the ARIA-style permission guardrails
  - stats: shape + graceful degradation
"""
import pytest

import profiles
from conftest import FakeClient


@pytest.fixture(autouse=True)
def _super_email(monkeypatch):
    monkeypatch.setattr(profiles, "SUPER_ADMIN_EMAIL", "hanz@wetreadwell.com")


def _use(monkeypatch, store=None):
    """Point profiles.get_client at a fresh FakeClient and return it."""
    client = FakeClient(store)
    monkeypatch.setattr(profiles, "get_client", lambda: client)
    return client


# ── ensure_profile ────────────────────────────────────────────────────
def test_ensure_profile_creates_super_admin_by_email(monkeypatch):
    _use(monkeypatch, {"profiles": []})
    row = profiles.ensure_profile("uid-1", "Hanz@WeTreadwell.com", "Hanz B")
    assert row["role"] == "super_admin"
    assert row["email"] == "hanz@wetreadwell.com"   # lowercased
    assert row["status"] == "active"


def test_ensure_profile_creates_regular_user(monkeypatch):
    _use(monkeypatch, {"profiles": []})
    row = profiles.ensure_profile("uid-2", "kyle@wetreadwell.com", "Kyle")
    assert row["role"] == "user"


def test_ensure_profile_preserves_existing_role(monkeypatch):
    # An existing admin signing in again must NOT be downgraded to user.
    store = {"profiles": [{"id": "uid-3", "email": "k@wetreadwell.com",
                           "full_name": "K", "role": "admin", "status": "active"}]}
    _use(monkeypatch, store)
    row = profiles.ensure_profile("uid-3", "k@wetreadwell.com", "K Updated")
    assert row["role"] == "admin"
    assert row["full_name"] == "K Updated"   # name still backfilled


def test_ensure_profile_promotes_existing_to_super_admin(monkeypatch):
    # hanz signed up before the bootstrap trigger existed → promote on next login.
    store = {"profiles": [{"id": "uid-h", "email": "hanz@wetreadwell.com",
                           "full_name": "Hanz", "role": "user", "status": "active"}]}
    _use(monkeypatch, store)
    row = profiles.ensure_profile("uid-h", "hanz@wetreadwell.com", "Hanz")
    assert row["role"] == "super_admin"
    assert store["profiles"][0]["role"] == "super_admin"   # persisted


# ── list_users: PostgREST filter-injection sanitization ────────────────
def test_search_sanitizes_filter_metacharacters(monkeypatch):
    client = _use(monkeypatch, {"profiles": []})
    # Crafted to break out of the ilike clause and inject an extra OR filter.
    profiles.list_users(search="x%),role.eq.super_admin,status.eq.active(")
    assert client.captures, "expected an .or_() filter to be issued"
    sent = client.captures[-1]
    # The code adds exactly ONE comma (between its two ilike clauses); a payload
    # comma would create a third filter. Parens would let in and()/or() groups.
    assert sent.count(",") == 1
    assert "(" not in sent and ")" not in sent
    assert "%)" not in sent


def test_search_passes_normal_terms_through(monkeypatch):
    client = _use(monkeypatch, {"profiles": []})
    profiles.list_users(search="kyle")
    assert client.captures[-1] == "email.ilike.%kyle%,full_name.ilike.%kyle%"


def test_search_allows_email_chars(monkeypatch):
    client = _use(monkeypatch, {"profiles": []})
    profiles.list_users(search="kyle@wetreadwell.com")
    assert "kyle@wetreadwell.com" in client.captures[-1]
    assert client.captures[-1].count(",") == 1


def test_list_users_role_filter(monkeypatch):
    store = {"profiles": [
        {"id": "1", "email": "a@wetreadwell.com", "role": "admin", "status": "active"},
        {"id": "2", "email": "b@wetreadwell.com", "role": "user", "status": "active"},
    ]}
    _use(monkeypatch, store)
    admins = profiles.list_users(role="admin")
    assert [u["id"] for u in admins] == ["1"]


# ── permission guardrails ──────────────────────────────────────────────
def test_can_act_blocks_super_admin_target():
    err = profiles._can_act({"id": "a", "role": "super_admin"},
                            {"id": "b", "role": "super_admin"})
    assert err and "protected" in err.lower()


def test_can_act_blocks_self():
    err = profiles._can_act({"id": "a", "role": "super_admin"},
                            {"id": "a", "role": "user"})
    assert err and "own account" in err.lower()


def test_can_act_admin_cannot_manage_admin():
    err = profiles._can_act({"id": "a", "role": "admin"},
                            {"id": "b", "role": "admin"})
    assert err and "super admin" in err.lower()


def test_can_act_super_admin_can_manage_admin():
    assert profiles._can_act({"id": "a", "role": "super_admin"},
                             {"id": "b", "role": "admin"}) is None


def test_can_act_missing_target():
    assert profiles._can_act({"id": "a", "role": "admin"}, None) == "User not found."


# ── set_role ───────────────────────────────────────────────────────────
def test_set_role_rejects_invalid_role(monkeypatch):
    _use(monkeypatch)
    out = profiles.set_role({"id": "a", "role": "super_admin"}, "b", "wizard")
    assert out["ok"] is False


def test_set_role_admin_cannot_grant_admin(monkeypatch):
    _use(monkeypatch)
    monkeypatch.setattr(profiles, "get_by_id",
                        lambda i: {"id": "b", "role": "user", "status": "active"})
    out = profiles.set_role({"id": "a", "role": "admin"}, "b", "admin")
    assert out["ok"] is False
    assert "super admin" in out["error"].lower()


def test_set_role_super_admin_grants_admin(monkeypatch):
    client = _use(monkeypatch, {"profiles": [{"id": "b", "role": "user", "status": "active"}]})
    monkeypatch.setattr(profiles, "get_by_id",
                        lambda i: {"id": "b", "role": "user", "status": "active"})
    out = profiles.set_role({"id": "a", "role": "super_admin"}, "b", "admin")
    assert out["ok"] is True and out["role"] == "admin"


def test_set_role_cannot_target_super_admin(monkeypatch):
    _use(monkeypatch)
    monkeypatch.setattr(profiles, "get_by_id",
                        lambda i: {"id": "b", "role": "super_admin"})
    out = profiles.set_role({"id": "a", "role": "super_admin"}, "b", "user")
    assert out["ok"] is False


# ── set_status ─────────────────────────────────────────────────────────
def test_set_status_rejects_unknown_status(monkeypatch):
    _use(monkeypatch)
    out = profiles.set_status({"id": "a", "role": "super_admin"}, "b", "frozen")
    assert out["ok"] is False


def test_set_status_pauses_user(monkeypatch):
    _use(monkeypatch, {"profiles": [{"id": "b", "role": "user", "status": "active"}]})
    monkeypatch.setattr(profiles, "get_by_id",
                        lambda i: {"id": "b", "role": "user", "status": "active"})
    out = profiles.set_status({"id": "a", "role": "admin"}, "b", "paused")
    assert out["ok"] is True and out["status"] == "paused"


# ── stats ──────────────────────────────────────────────────────────────
def test_stats_shape(monkeypatch):
    store = {
        "profiles": [
            {"id": "1", "role": "super_admin"}, {"id": "2", "role": "admin"},
            {"id": "3", "role": "user"},
        ],
        "drafts": [{"id": "d1"}, {"id": "d2"}],
        "events": [{"id": 1, "action": "generated"}, {"id": 2, "action": "created"}],
    }
    _use(monkeypatch, store)
    s = profiles.stats()
    assert set(s) == {"users", "admins", "projects", "proposals_generated"}
    assert s["users"] == 3
    assert s["admins"] == 2
    assert s["projects"] == 2
    assert s["proposals_generated"] == 1
