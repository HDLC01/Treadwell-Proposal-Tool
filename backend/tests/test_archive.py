"""Active/inactive (archive) status — Kyle's Projects-tab active/inactive filter.

The flag lives inside the `data` blob (`data.archived`) so there's no schema
migration and it works the same on cloud Supabase (prod) and the VPS PostgREST
(staging). drafts.set_archived() read-modify-writes the blob WITHOUT bumping
updated_at; the /api/draft/{id}/archive endpoint wires it up.
"""
from fastapi.testclient import TestClient

import drafts
import main

client = TestClient(main.app)


def _seed(fake_supabase):
    store = {"drafts": [
        {"id": "a", "data": {"project_name": "Won Job"}, "owner_email": "u@x.com",
         "created_at": "2026-01-01", "updated_at": "2026-01-02", "deleted_at": None},
    ], "events": []}
    return fake_supabase(store), store


# ── drafts.py logic (against the in-memory Supabase fake) ───────────────
def test_set_archived_flips_flag_and_logs(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)

    assert drafts.set_archived("a", True, "actor@x.com") is True
    assert store["drafts"][0]["data"]["archived"] is True
    # archiving must NOT reorder the list — updated_at stays put
    assert store["drafts"][0]["updated_at"] == "2026-01-02"
    assert any(e["action"] == "archived" and e["detail"]["project_name"] == "Won Job"
               for e in store["events"])

    assert drafts.set_archived("a", False, "actor@x.com") is True
    assert store["drafts"][0]["data"]["archived"] is False
    assert any(e["action"] == "unarchived" for e in store["events"])


def test_set_archived_missing_project_returns_false(fake_supabase, monkeypatch):
    fake, _ = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_archived("nope", True) is False


# ── pure helpers: text-or-bool coercion + summary projection ───────────
def test_truthy_coerces_postgrest_text_and_bool():
    assert drafts._truthy(True) is True
    assert drafts._truthy("true") is True
    assert drafts._truthy("t") is True
    assert drafts._truthy(False) is False
    assert drafts._truthy("false") is False
    assert drafts._truthy(None) is False


def test_summary_surfaces_archived_from_blob():
    row = {"id": "z", "data": {"project_name": "P", "archived": True},
           "owner_email": "u@x.com"}
    assert drafts._summary(row)["archived"] is True
    row2 = {"id": "z2", "data": {"project_name": "P2"}, "owner_email": "u@x.com"}
    assert drafts._summary(row2)["archived"] is False


# ── endpoint wiring (monkeypatch the drafts layer) ──────────────────────
def test_archive_endpoint_wires_through(monkeypatch):
    seen = {}

    def fake_set(i, archived, actor=None):
        seen.update(id=i, archived=archived, actor=actor)
        return True

    monkeypatch.setattr(main.drafts, "set_archived", fake_set)
    r = client.post("/api/draft/proj-9/archive", json={"archived": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["archived"] is True and body["existed"] is True
    assert seen == {"id": "proj-9", "archived": True, "actor": "tester@wetreadwell.com"}


def test_archive_endpoint_defaults_to_true(monkeypatch):
    seen = {}
    monkeypatch.setattr(main.drafts, "set_archived",
                        lambda i, archived, actor=None: seen.update(archived=archived) or True)
    r = client.post("/api/draft/proj-x/archive", json={})
    assert r.status_code == 200 and seen["archived"] is True
