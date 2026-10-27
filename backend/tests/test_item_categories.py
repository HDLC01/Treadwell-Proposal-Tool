"""Item categories: the headings a work type's materials are grouped under on the v2 estimate.

Hanz, 2026-10-27: "For the Items we must have another column which is category. The Categories will be
set in the Administration tab, so for example for epoxy we have Patch, Epoxy Liquids, Extras, Cove, just
like the sheet. Then we also need to separate these categories in the Estimates."

Claims, each executed through the real module or the real app:
  * the STORE (item_categories.py): an absent or garbled file reads as Kyle's sheet headings; a save keeps
    the order it was given; a blank or repeated name is dropped; every entry keeps its id across a rename
    and a new one gets a fresh id, so a RENAME reaches every material filed under it and a REMOVE leaves
    them uncategorised, both with no write to a material.
  * the ROUTES: anyone signed in reads the lists (on their own route and riding on /api/library/items);
    only an admin, or a member granted the Items and Assemblies tab, writes them.
  * the MATERIAL'S CATEGORY (library.py `material_categories`): written only when a request carries it, so
    a database without backend/ops/item_categories.sql is never sent the column; read back as {} when the
    column is absent; survives a jsonb reload in any key order; and a database without the column answers
    a readable 400 instead of a 500.
"""
import json

import pytest
from fastapi.testclient import TestClient

import item_categories as ic
import library
import main
import markup
import special_permissions as sp

MARISOL = "marisol@wetreadwell.com"


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(ic, "_FILE", tmp_path / "item_categories.json")
    monkeypatch.setattr(ic, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(sp, "_FILE", tmp_path / "special_permissions.json")
    monkeypatch.setattr(sp, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    main._profile_cache_clear()
    yield
    main._profile_cache_clear()


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"library_items": [], "library_assemblies": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(library, "get_client", lambda: fake)
    return st


def _as(monkeypatch, role, email=MARISOL):
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "somebody-else@wetreadwell.com")
    monkeypatch.setattr(main, "_user_email", lambda request: email)
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": email, "role": role, "status": "active"})
    main._profile_cache_clear()
    return TestClient(main.app)


def _names(store, wt):
    return [c["name"] for c in store["work_types"][wt]]


# ── the store ────────────────────────────────────────────────────────────────
def test_the_work_types_are_markups_five_in_hanzs_order():
    assert set(ic.WORK_TYPES) == set(markup.TABS)
    assert ic.WORK_TYPES == ("epoxy", "polish", "gyp", "seal", "leveling")


def test_an_unsaved_store_reads_as_the_sheets_headings():
    """Kyle's Epoxy and Polish tabs, word for word and in order; the other three have none until set."""
    st = ic.load()
    assert st["seeded"] is True
    assert _names(st, "epoxy") == ["Patch", "Epoxy Liquids", "Extras", "Cove"]
    assert _names(st, "polish") == ["Patch", "Floor", "Dye", "Joint Filler"]
    assert st["work_types"]["gyp"] == st["work_types"]["seal"] == st["work_types"]["leveling"] == []


@pytest.mark.parametrize("raw", ["{not json", "[]", '{"work_types": 3}', ""])
def test_a_garbled_file_reads_as_the_sheets_headings(raw):
    ic._FILE.write_text(raw, encoding="utf-8")
    assert _names(ic.load(), "epoxy") == ["Patch", "Epoxy Liquids", "Extras", "Cove"]


def test_a_save_keeps_its_order_and_a_reload_reads_it_back():
    seeded = ic.load()["work_types"]
    flipped = dict(seeded, polish=list(reversed(seeded["polish"])))
    saved = ic.save(flipped, "hanz@wetreadwell.com")
    assert _names(saved, "polish") == ["Joint Filler", "Dye", "Floor", "Patch"]
    again = ic.load()
    assert again["seeded"] is False and again["updated_by"] == "hanz@wetreadwell.com"
    assert _names(again, "polish") == ["Joint Filler", "Dye", "Floor", "Patch"]
    assert [c["id"] for c in again["work_types"]["polish"]] == [c["id"] for c in flipped["polish"]]


def test_blank_and_repeated_names_are_dropped_and_new_entries_get_ids():
    saved = ic.save({"gyp": [{"name": "  Bags "}, "bags", {"name": "   "}, {"id": "BAD ID!", "name": "Sand"},
                             {"name": "Sound   mat"}], "nonsense": [{"name": "X"}]})
    gyp = saved["work_types"]["gyp"]
    assert [c["name"] for c in gyp] == ["Bags", "Sand", "Sound mat"]
    assert all(ic.ID_RE.match(c["id"]) and c["id"].startswith("gyp-") for c in gyp)
    assert len({c["id"] for c in gyp}) == 3
    assert "nonsense" not in saved["work_types"]


def test_an_id_used_twice_is_given_a_fresh_one_so_two_headings_never_share_it():
    saved = ic.save({"epoxy": [{"id": "x-1", "name": "A"}], "polish": [{"id": "x-1", "name": "B"}]})
    assert saved["work_types"]["epoxy"][0]["id"] == "x-1"
    assert saved["work_types"]["polish"][0]["id"] != "x-1"


def test_a_rename_reaches_the_material_and_a_remove_leaves_it_uncategorised():
    """The material stores the id; the name is looked up. So neither edit writes to a material."""
    item = {"material_categories": {"epoxy": "epoxy-patch", "polish": "polish-floor"}}
    st = ic.load()["work_types"]
    renamed = dict(st, epoxy=[dict(c, name="Patch and Prep") if c["id"] == "epoxy-patch" else c
                              for c in st["epoxy"]])
    ic.save(renamed)
    assert ic.name_of("epoxy", item["material_categories"]["epoxy"]) == "Patch and Prep"
    ic.save(dict(renamed, polish=[c for c in renamed["polish"] if c["id"] != "polish-floor"]))
    assert ic.name_of("polish", item["material_categories"]["polish"]) is None
    # ...and adding the same name back is a NEW heading: the removal is not silently undone.
    again = ic.save(dict(ic.load()["work_types"], polish=ic.load()["work_types"]["polish"] + [{"name": "Floor"}]))
    assert [c for c in again["work_types"]["polish"] if c["name"] == "Floor"][0]["id"] != "polish-floor"


def test_a_failed_write_raises_rather_than_pretending(monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ic.atomic_json, "write_json", boom)
    with pytest.raises(ic.ItemCategoriesWriteError):
        ic.save(ic.SEED)


# ── the routes ───────────────────────────────────────────────────────────────
def test_anybody_signed_in_reads_the_lists(monkeypatch):
    r = _as(monkeypatch, "user").get("/api/item-categories")
    assert r.status_code == 200
    body = r.json()
    assert body["order"] == list(ic.WORK_TYPES) and body["labels"]["gyp"] == "Gyp"
    assert [c["name"] for c in body["work_types"]["epoxy"]] == ["Patch", "Epoxy Liquids", "Extras", "Cove"]


def test_a_member_cannot_change_them(monkeypatch):
    r = _as(monkeypatch, "user").put("/api/item-categories", json={"work_types": {"gyp": [{"name": "Bags"}]}})
    assert r.status_code == 403
    assert not ic._FILE.exists(), "a refused write reached the store"


def test_an_admin_can_and_the_answer_is_the_stored_copy(monkeypatch):
    r = _as(monkeypatch, "admin").put("/api/item-categories",
                                       json={"work_types": {"gyp": [{"name": "Bags"}, {"name": "Sand"}]}})
    assert r.status_code == 200
    assert [c["name"] for c in r.json()["work_types"]["gyp"]] == ["Bags", "Sand"]
    assert r.json()["work_types"]["epoxy"] == [], "the PUT replaces every list; one left out is emptied"
    assert r.json()["updated_by"] == MARISOL
    assert [c["name"] for c in ic.load()["work_types"]["gyp"]] == ["Bags", "Sand"]


def test_a_member_granted_the_items_and_assemblies_tab_can(monkeypatch):
    sp.save({MARISOL: [sp.LIBRARY]})
    r = _as(monkeypatch, "user").put("/api/item-categories", json={"work_types": {"seal": ["Sealer"]}})
    assert r.status_code == 200 and [c["name"] for c in r.json()["work_types"]["seal"]] == ["Sealer"]


def test_an_unknown_field_is_refused(monkeypatch):
    r = _as(monkeypatch, "admin").put("/api/item-categories", json={"work_types": {}, "grants": {}})
    assert r.status_code == 422


def test_a_failed_save_is_a_500_not_a_cheerful_200(monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(ic.atomic_json, "write_json", boom)
    r = _as(monkeypatch, "admin").put("/api/item-categories", json={"work_types": {}})
    assert r.status_code == 500


def test_the_lists_ride_on_the_items_read(store, monkeypatch):
    """Both pages that show materials need them, and this saves each a second request."""
    body = _as(monkeypatch, "user").get("/api/library/items").json()
    assert body["items"] == []
    assert [c["name"] for c in body["item_categories"]["work_types"]["polish"]] == ["Patch", "Floor", "Dye",
                                                                                     "Joint Filler"]


def test_an_unreadable_store_never_costs_the_items_read(store, monkeypatch):
    def boom():
        raise RuntimeError("bad volume")
    monkeypatch.setattr(ic, "load", boom)
    r = _as(monkeypatch, "user").get("/api/library/items")
    assert r.status_code == 200 and r.json()["item_categories"] is None


# ── a material's category ────────────────────────────────────────────────────
def _mk(**kw):
    body = {"name": "OPF", "unit": "Gallon", "unit_cost": 85.3827, "coverage": 275}
    body.update(kw)
    return library.create_item(body, "hanz@wetreadwell.com")


def test_the_column_is_written_only_when_the_request_carries_it(store):
    """A database without backend/ops/item_categories.sql must never be sent the column."""
    _mk()
    assert "material_categories" not in store["library_items"][0]
    assert "material_categories" not in library.validate_item({"name": "OPF", "unit_cost": 3}, partial=True)
    assert library.validate_item({"material_categories": {"epoxy": "epoxy-patch"}},
                                 partial=True) == {"material_categories": {"epoxy": "epoxy-patch"}}


def test_a_row_without_the_column_reads_as_uncategorised(store):
    it = _mk()
    assert library.get_item(it["id"])["material_categories"] == {}


def test_only_known_work_types_and_real_ids_are_kept():
    out = library.validate_item({"material_categories": {"Epoxy": "epoxy-patch", "polish": "", "nope": "x",
                                                         "gyp": "NOT AN ID!", "seal": 7}}, partial=True)
    assert out == {"material_categories": {"epoxy": "epoxy-patch"}}
    assert library.validate_item({"material_categories": {}}, partial=True) == {"material_categories": None}


def test_a_category_set_through_the_api_reads_back_and_survives_a_jsonb_reload(store, monkeypatch):
    """jsonb hands an object back key-sorted, so the map comes back in another order; it must mean the same."""
    it = _mk()
    c = _as(monkeypatch, "user")
    r = c.patch("/api/library/items/%s" % it["id"],
                json={"material_categories": {"gyp": "gyp-bags", "epoxy": "epoxy-extras"}})
    assert r.status_code == 200
    assert r.json()["item"]["material_categories"] == {"epoxy": "epoxy-extras", "gyp": "gyp-bags"}
    # A reload: the stored map round-trips through JSON with its keys in jsonb's order (length, then bytes),
    # which puts "gyp" before "epoxy" - the opposite of the store's own order.
    row = store["library_items"][0]
    raw = row["material_categories"]
    row["material_categories"] = json.loads(json.dumps(dict(sorted(raw.items(), key=lambda kv: (len(kv[0]), kv[0])))))
    listed = c.get("/api/library/items").json()["items"][0]["material_categories"]
    assert list(row["material_categories"]) == ["gyp", "epoxy"], "the reload did not reorder: not a real round trip"
    assert listed == {"epoxy": "epoxy-extras", "gyp": "gyp-bags"}
    assert list(listed) == ["epoxy", "gyp"], "read back in the store's own order, whatever jsonb did"


def test_a_category_alone_moves_no_price_date(store, monkeypatch):
    it = _mk()
    _as(monkeypatch, "user").patch("/api/library/items/%s" % it["id"],
                                   json={"material_categories": {"epoxy": "epoxy-patch"}})
    assert store["library_items"][0].get("cost_updated_at") is None


def test_a_database_without_the_column_answers_a_readable_400(store, monkeypatch):
    it = _mk()
    real = library.get_client()

    class Missing:
        def __init__(self, inner):
            self.inner = inner

        def table(self, name):
            t = self.inner.table(name)
            update = t.update

            def refusing(patch):
                if "material_categories" in patch:
                    raise RuntimeError("Could not find the 'material_categories' column of 'library_items'")
                return update(patch)
            t.update = refusing
            return t
    monkeypatch.setattr(library, "get_client", lambda: Missing(real))
    r = _as(monkeypatch, "user").patch("/api/library/items/%s" % it["id"],
                                       json={"material_categories": {"epoxy": "epoxy-patch"}})
    assert r.status_code == 400 and "item_categories.sql" in r.json()["detail"]
    # ...and every other edit on that database still saves.
    assert _as(monkeypatch, "user").patch("/api/library/items/%s" % it["id"],
                                          json={"unit_cost": 90}).status_code == 200
