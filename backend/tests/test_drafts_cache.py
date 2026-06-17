"""In-memory cache for the project lists.

`drafts.list_drafts`/`list_trashed` serve from a module-level TTLCache to spare
the Supabase/PostgREST round-trip on every Projects-dashboard load. Any write
(save/trash/restore/archive/delete) clears the cache so changes show up
immediately. Empty/failed reads are never cached. (conftest clears the cache
around every test, so these run in isolation.)
"""
import drafts


def _seed(fake_supabase):
    store = {"drafts": [
        {"id": "a", "data": {"project_name": "Alpha"}, "owner_email": "u@x.com",
         "created_at": "2026-01-01", "updated_at": "2026-01-02", "deleted_at": None},
    ], "events": []}
    return fake_supabase(store), store


def test_list_is_cached_then_invalidated_on_write(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)

    # first call populates the cache
    assert {p["id"] for p in drafts.list_drafts()} == {"a"}

    # add a row directly in the store (NOT via a write fn) — the cache should
    # still serve the old list, proving reads come from cache.
    store["drafts"].append(
        {"id": "b", "data": {"project_name": "Bravo"}, "owner_email": "u@x.com",
         "created_at": "2026-01-03", "updated_at": "2026-01-04", "deleted_at": None})
    assert {p["id"] for p in drafts.list_drafts()} == {"a"}, "stale read proves cache served"

    # any write clears the cache → next read reflects the new row
    drafts.trash_draft("nope")                       # no row matches, but still clears
    assert {p["id"] for p in drafts.list_drafts()} == {"a", "b"}


def test_save_draft_invalidates(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert {p["id"] for p in drafts.list_drafts()} == {"a"}            # caches [a]
    drafts.save_draft("c", {"project_name": "Cee"}, "u@x.com")        # creates + clears
    assert {p["id"] for p in drafts.list_drafts()} == {"a", "c"}


def test_empty_result_not_cached(fake_supabase, monkeypatch):
    store = {"drafts": [], "events": []}
    fake = fake_supabase(store)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.list_drafts() == []                                 # empty → NOT cached
    store["drafts"].append(
        {"id": "z", "data": {"project_name": "Z"}, "owner_email": "u@x.com",
         "created_at": "2026-01-01", "updated_at": "2026-01-02", "deleted_at": None})
    # no explicit write/invalidation — it shows up because [] was never cached
    assert {p["id"] for p in drafts.list_drafts()} == {"z"}, "empty list must not be cached"
