"""Trash / soft-delete: drafts.py logic + the /api/draft & /api/trash endpoints.

drafts.py talks to Supabase via get_client(); we swap in the in-memory
FakeClient (conftest) so the soft-delete logic is exercised with no network.
Endpoint tests monkeypatch the drafts layer to assert wiring + the
trash-vs-purge branch on DELETE /api/draft/{id}.
"""
from fastapi.testclient import TestClient

import drafts
import main

client = TestClient(main.app)


# ── drafts.py logic (against the in-memory Supabase fake) ───────────────
def _seed(fake_supabase):
    store = {"drafts": [
        {"id": "a", "data": {"project_name": "Active One"}, "owner_email": "u@x.com",
         "created_at": "2026-01-01", "updated_at": "2026-01-02", "deleted_at": None},
        {"id": "b", "data": {"project_name": "Active Two"}, "owner_email": "u@x.com",
         "created_at": "2026-01-03", "updated_at": "2026-01-04", "deleted_at": None},
    ], "events": []}
    return fake_supabase(store), store


def test_trash_then_restore_roundtrip(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)

    # Active list shows both; trash is empty.
    assert {p["id"] for p in drafts.list_drafts()} == {"a", "b"}
    assert drafts.list_trashed() == []

    # Soft-delete "a" → it leaves the active list and appears in trash.
    assert drafts.trash_draft("a", "actor@x.com") is True
    assert store["drafts"][0]["deleted_at"] is not None
    assert {p["id"] for p in drafts.list_drafts()} == {"b"}
    trash = drafts.list_trashed()
    assert [p["id"] for p in trash] == ["a"]
    assert trash[0]["deleted_at"] is not None
    # logged a 'trashed' event with the project name
    assert any(e["action"] == "trashed" and e["detail"]["project_name"] == "Active One"
               for e in store["events"])

    # Restore "a" → back to active, gone from trash, deleted_at cleared.
    assert drafts.restore_draft("a", "actor@x.com") is True
    assert store["drafts"][0]["deleted_at"] is None
    assert {p["id"] for p in drafts.list_drafts()} == {"a", "b"}
    assert drafts.list_trashed() == []
    assert any(e["action"] == "restored" for e in store["events"])


def test_purge_hard_deletes(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.trash_draft("b")
    assert drafts.delete_draft("b") is True          # permanent
    assert all(r["id"] != "b" for r in store["drafts"])
    assert drafts.list_trashed() == []               # nothing left in trash


def test_trash_missing_project_returns_false(fake_supabase, monkeypatch):
    fake, _ = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.trash_draft("nope") is False
    assert drafts.restore_draft("nope") is False


# ── endpoint wiring (monkeypatch the drafts layer) ──────────────────────
def test_delete_endpoint_soft_deletes_by_default(monkeypatch):
    calls = {}
    monkeypatch.setattr(main.drafts, "trash_draft",
                        lambda i, actor=None: calls.setdefault("trash", (i, actor)) or True)
    monkeypatch.setattr(main.drafts, "delete_draft",
                        lambda i: calls.setdefault("purge", i) or True)
    r = client.delete("/api/draft/proj-1")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["trashed"] is True and "permanent" not in body
    assert calls["trash"][0] == "proj-1" and "purge" not in calls


def test_delete_endpoint_permanent_purges(monkeypatch):
    calls = {}
    monkeypatch.setattr(main.drafts, "trash_draft",
                        lambda i, actor=None: calls.setdefault("trash", i) or True)
    monkeypatch.setattr(main.drafts, "delete_draft",
                        lambda i: calls.setdefault("purge", i) or True)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    r = client.delete("/api/draft/proj-2?permanent=true")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["permanent"] is True
    assert calls["purge"] == "proj-2" and "trash" not in calls


def test_restore_endpoint(monkeypatch):
    seen = {}

    def fake_restore(i, actor=None):
        seen.update(id=i, actor=actor)
        return True

    monkeypatch.setattr(main.drafts, "restore_draft", fake_restore)
    r = client.post("/api/draft/proj-3/restore")
    assert r.status_code == 200 and r.json()["existed"] is True
    assert seen["id"] == "proj-3" and seen["actor"] == "tester@wetreadwell.com"


def test_trash_list_endpoint(monkeypatch):
    monkeypatch.setattr(main.drafts, "list_trashed",
                        lambda: [{"id": "x", "project_name": "Gone", "deleted_at": "2026-02-01"}])
    r = client.get("/api/trash")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["projects"][0]["id"] == "x"
