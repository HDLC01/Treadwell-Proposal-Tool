"""Admin API gate + /api/me identity endpoint.

The autouse _bypass_auth fixture authenticates every request as
tester@wetreadwell.com (so request.state.user_email is set). These tests then
control what the profiles layer reports for that user to exercise the
_require_admin gate and the /api/me profile upsert — no live Supabase needed.
"""
from fastapi.testclient import TestClient

import main
import profiles
import supabase_client

client = TestClient(main.app)


# ── _require_admin gate ────────────────────────────────────────────────
def test_admin_endpoint_blocks_regular_user(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": e, "role": "user"})
    r = client.get("/api/admin/users")
    assert r.status_code == 403


def test_admin_endpoint_blocks_unknown_user(monkeypatch):
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "someone-else@wetreadwell.com")
    monkeypatch.setattr(profiles, "get_by_email", lambda e: None)
    r = client.get("/api/admin/stats")
    assert r.status_code == 403


def test_admin_endpoint_allows_admin(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "a1", "email": e, "role": "admin"})
    monkeypatch.setattr(profiles, "list_users", lambda search="", role="": [])
    r = client.get("/api/admin/users")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_admin_endpoint_allows_super_admin_by_email_fallback(monkeypatch):
    # Profile row not created yet, but the email matches SUPER_ADMIN_EMAIL →
    # anti-lockout fallback must still grant access.
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "tester@wetreadwell.com")
    monkeypatch.setattr(profiles, "get_by_email", lambda e: None)
    monkeypatch.setattr(profiles, "stats",
                        lambda: {"users": 0, "admins": 0, "projects": 0, "proposals_generated": 0})
    r = client.get("/api/admin/stats")
    assert r.status_code == 200


def test_set_role_endpoint_runs_for_admin(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "a1", "email": e, "role": "super_admin"})
    captured = {}

    def fake_set_role(actor, target_id, role):
        captured.update(actor=actor, target=target_id, role=role)
        return {"ok": True, "role": role}

    monkeypatch.setattr(profiles, "set_role", fake_set_role)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    r = client.patch("/api/admin/users/target-1/role", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert captured["target"] == "target-1" and captured["role"] == "admin"


# ── admin: delete a project ────────────────────────────────────────────
def test_delete_project_blocked_for_non_admin(monkeypatch):
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "nobody@wetreadwell.com")
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": e, "role": "user"})
    assert client.delete("/api/admin/projects/proj-1").status_code == 403


def test_delete_project_trashes_for_admin(monkeypatch):
    # Admin "delete" is now a SOFT delete — it moves the project to Trash
    # (restorable) via drafts.trash_draft, not a hard delete.
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "a1", "email": e, "role": "admin"})
    trashed = {}

    def fake_trash(i, actor_email=None):
        trashed.update(id=i, actor=actor_email)
        return True

    monkeypatch.setattr(main.drafts, "trash_draft", fake_trash)
    r = client.delete("/api/admin/projects/proj-9")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["existed"] is True and body["trashed"] is True
    assert trashed["id"] == "proj-9" and trashed["actor"] == "tester@wetreadwell.com"


# ── /api/me ────────────────────────────────────────────────────────────
def test_me_upserts_profile_from_claims(monkeypatch):
    monkeypatch.setattr(supabase_client, "verify_token_claims", lambda auth: {
        "sub": "uid-42", "email": "tester@wetreadwell.com",
        "user_metadata": {"full_name": "Test Tester"},
    })
    seen = {}

    def fake_ensure(user_id, email, name):
        seen.update(user_id=user_id, email=email, name=name)
        return {"email": email, "full_name": name, "role": "super_admin", "status": "active"}

    monkeypatch.setattr(profiles, "ensure_profile", fake_ensure)
    r = client.get("/api/me")
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "super_admin"
    assert body["name"] == "Test Tester"
    assert seen == {"user_id": "uid-42", "email": "tester@wetreadwell.com", "name": "Test Tester"}


def test_me_falls_back_when_claims_unavailable(monkeypatch):
    # verify_token_claims blows up (e.g. no real token in test) → /api/me must
    # still answer using the gate email + get_by_email, never 500.
    def boom(auth):
        raise supabase_client.AuthError(401, "no token")

    monkeypatch.setattr(supabase_client, "verify_token_claims", boom)
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"email": e, "full_name": "Fallback", "role": "user", "status": "active"})
    r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["role"] == "user"
    assert r.json()["name"] == "Fallback"
