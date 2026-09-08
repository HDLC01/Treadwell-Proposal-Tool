"""Who made a library row, and who last changed it.

Hanz, 2026-09-04: "in the items tab we must put the name of who created it and who edited it."
`owner_email` already answered the first half. `updated_by` is the second, and these tests pin the
three ways it can be wrong in a way that still LOOKS like a name:

  * **A forged one.** The whole point of the field is accountability for a price somebody typed,
    so it is stamped from the authenticated request and never from the body. A client that PATCHes
    `updated_by` must not be able to sign a colleague's name to its own edit.
  * **A stale one.** `updated_by` describes the write that moved `updated_at`. If an edit lands
    without a name attached, the honest value is "unknown" — leaving the previous editor there
    attributes a change to a person who did not make it, which is exactly the lie a
    `not null default` would have baked into every legacy row.
  * **A confused one.** `cost_updated_at` is a PRICE revision, deliberately separate from
    `updated_at` (test_items_and_assemblies.py owns that rule). Editing a spelling must name the
    editor without making a stale number look fresh, and the two stamps must not be conflated.

An assembly LINE edit is an edit. It PATCHes the whole `lines` array through update_assembly, so
adding a coat or changing a coverage names whoever did it.

Nothing here is migrated. A row typed before the column existed is read-shaped to empty, so the
tab shows "—" without an UPDATE touching hand-typed data. Runs against the in-memory Supabase
fake, like test_library.py — conftest refuses to let the suite reach the production data store.
"""
import pathlib
import re

import pytest
from fastapi.testclient import TestClient

import library
import main

client = TestClient(main.app)

BACKEND = pathlib.Path(__file__).resolve().parents[1]

# conftest's auth bypass authenticates every request as this person, so it is who the ENDPOINT
# tests below must end up naming.
SIGNED_IN = "tester@wetreadwell.com"

KYLE = "kyle@wetreadwell.com"
WILL = "will@wetreadwell.com"


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"library_items": [], "library_assemblies": [], "library_vendors": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(library, "get_client", lambda: fake)
    return st


def _mk_item(owner=KYLE, **kw):
    body = {"name": "OPF", "unit": "Gallon", "unit_cost": 85.3827, "coverage": 275}
    body.update(kw)
    return library.create_item(body, owner)


def _mk_asm(owner=KYLE, **kw):
    body = {"name": "MACRO Flake", "unit": "SF"}
    body.update(kw)
    return library.create_assembly(body, owner)


# ── the create records who made it ────────────────────────────────────
def test_a_new_material_records_who_made_it(store):
    it = _mk_item()
    assert it["owner_email"] == KYLE
    # The create IS the first write and it stamped `updated_at`, so `updated_by` names the same
    # person. Two columns describing one write must not disagree.
    assert it["updated_by"] == KYLE
    assert it["created_at"] == it["updated_at"]


def test_a_new_assembly_records_who_made_it(store):
    asm = _mk_asm()
    assert asm["owner_email"] == KYLE and asm["updated_by"] == KYLE


def test_an_email_is_stored_one_way_so_the_two_columns_compare(store):
    """The tab puts them side by side. "Kyle@..." created it / "kyle@..." edited it would read as
    two different people, so both go through the same normalisation."""
    it = _mk_item(owner="  Kyle@WeTreadwell.com ")
    assert it["owner_email"] == KYLE and it["updated_by"] == KYLE
    got = library.update_item(it["id"], {"notes": "checked"}, "  WILL@WeTreadwell.COM ")
    assert got["updated_by"] == WILL


def test_a_creator_with_no_identity_is_stored_as_unknown_not_as_a_blank_name(store):
    """A create from a script has no person behind it. NULL, so the tab shows "—"."""
    it = library.create_item({"name": "Densifier"}, None)
    assert it["owner_email"] == "" and it["updated_by"] == ""
    assert store["library_items"][0]["owner_email"] is None
    assert store["library_items"][0]["updated_by"] is None


# ── the edit records who changed it ───────────────────────────────────
def test_an_edit_names_the_editor_without_rewriting_who_made_it(store):
    """The two facts are independent: Will correcting Kyle's price does not make it Will's row."""
    it = _mk_item(owner=KYLE)
    got = library.update_item(it["id"], {"unit_cost": 91.5}, WILL)
    assert got["updated_by"] == WILL, "the edit did not name the person who made it"
    assert got["owner_email"] == KYLE, "an edit reassigned who created the row"


def test_every_kind_of_edit_names_the_editor(store):
    """`updated_by` answers "who moved `updated_at`", so anything that moves one moves the other.
    A patch that names only some columns is the normal case — the tab saves per field."""
    it = _mk_item(owner=KYLE)
    for patch in ({"name": "OPF Primer"}, {"vendor": "Sherwin-Williams"}, {"buy_qty": 5},
                  {"unit": "Gallon"}, {"notes": "was mispriced"}, {"coverage": 300},
                  {"unit_cost": 91.5}, {"divisions": ["Epoxy"]}):
        before = library.get_item(it["id"])["updated_at"]
        got = library.update_item(it["id"], patch, WILL)
        assert got["updated_by"] == WILL, "editing %s left no name" % list(patch)[0]
        assert got["updated_at"] > before, (
            "editing %s did not move updated_at, so updated_by is describing an older write"
            % list(patch)[0])


def test_editing_an_assembly_line_is_an_edit(store):
    """The edit that actually happens on this page. A line change PATCHes the WHOLE lines array
    through the same update path, so adding a coat names whoever added it."""
    asm = _mk_asm(owner=KYLE)
    got = library.update_assembly(asm["id"], {"lines": [
        {"item_id": "i1", "role": "1st BC", "coverage": 275}]}, WILL)
    assert got["lines"] and got["updated_by"] == WILL
    assert got["owner_email"] == KYLE


def test_renaming_an_assembly_is_an_edit(store):
    asm = _mk_asm(owner=KYLE)
    assert library.update_assembly(asm["id"], {"name": "MACRO Flake HF"},
                                   WILL)["updated_by"] == WILL


def test_an_edit_by_a_caller_we_cannot_name_says_unknown_not_the_last_person(store):
    """The stale-name trap. An import script's write is still a write, and the row must not go on
    claiming Kyle made a change he never saw. "Unknown" is a fact; his name would not be."""
    it = _mk_item(owner=KYLE)
    got = library.update_item(it["id"], {"unit_cost": 91.5})       # nobody named
    assert got["updated_by"] == "", "an unattributable edit kept the previous editor's name"
    assert store["library_items"][0]["updated_by"] is None
    assert got["owner_email"] == KYLE, "who created it is still recorded"


def test_an_unattributable_assembly_edit_says_unknown_too(store):
    asm = _mk_asm(owner=KYLE)
    library.update_assembly(asm["id"], {"lines": [{"role": "A"}]}, WILL)
    got = library.update_assembly(asm["id"], {"lines": [{"role": "B"}]})
    assert got["updated_by"] == ""


def test_a_patch_that_changes_nothing_does_not_reassign_authorship(store):
    """The debounced save re-sends fields as somebody tabs out, and an empty patch is a no-op that
    never reaches the store. Nobody edited it, so nobody's name goes on it."""
    it = _mk_item(owner=KYLE)
    library.update_item(it["id"], {"unit_cost": 91.5}, WILL)
    stamped = library.get_item(it["id"])
    assert library.update_item(it["id"], {}, "somebody@wetreadwell.com")["updated_by"] == WILL
    assert library.get_item(it["id"])["updated_at"] == stamped["updated_at"]


def test_a_version_check_on_its_own_is_not_an_edit(store):
    """`expected_updated_at` is not a column. A payload carrying only that changes nothing, so it
    must not restamp who edited the assembly."""
    asm = _mk_asm(owner=KYLE)
    library.update_assembly(asm["id"], {"lines": [{"role": "A"}]}, WILL)
    cur = library.get_assembly(asm["id"])
    got = library.update_assembly(asm["id"], {"expected_updated_at": cur["updated_at"]},
                                  "somebody@wetreadwell.com")
    assert got["updated_by"] == WILL
    assert got["updated_at"] == cur["updated_at"]


def test_a_refused_stale_write_does_not_change_who_edited_it(store):
    """A refusal that still writes is worse than no check at all — test_library.py makes that
    point about the lines themselves. The same has to hold for the name attached to them."""
    asm = _mk_asm(owner=KYLE)
    library.update_assembly(asm["id"], {"lines": [{"role": "Top Coat"}]}, WILL)
    with pytest.raises(library.StaleWrite):
        library.update_assembly(asm["id"], {"lines": [], "expected_updated_at": asm["updated_at"]},
                                "intruder@wetreadwell.com")
    assert library.get_assembly(asm["id"])["updated_by"] == WILL


# ── nobody can sign somebody else's name ──────────────────────────────
def test_updated_by_is_not_a_column_a_caller_may_write():
    """Server-set. It is the answer to "who changed this price", so a body that can set it is a
    body that can blame a colleague."""
    assert "updated_by" not in library.ITEM_WRITABLE
    assert "updated_by" not in library.ASM_WRITABLE
    # And the enforcement, which is the validator rather than those tuples: an unknown key is
    # dropped, not stored.
    assert "updated_by" not in library.validate_item(
        {"name": "x", "updated_by": KYLE}, partial=True)
    assert "updated_by" not in library.validate_assembly(
        {"name": "x", "updated_by": KYLE}, partial=True)
    assert "owner_email" not in library.validate_item({"name": "x", "owner_email": KYLE})


def test_a_client_cannot_claim_somebody_else_made_the_edit(store):
    """Executed, not read: the field is dropped by the validator, so what reaches the store is
    the authenticated caller and nothing else."""
    it = _mk_item(owner=KYLE)
    got = library.update_item(it["id"],
                              {"unit_cost": 91.5, "updated_by": KYLE, "owner_email": KYLE},
                              WILL)
    assert got["updated_by"] == WILL, "a payload field overwrote the authenticated editor"
    assert store["library_items"][0]["updated_by"] == WILL


def test_a_client_cannot_claim_somebody_else_made_the_edit_to_an_assembly(store):
    asm = _mk_asm(owner=KYLE)
    got = library.update_assembly(asm["id"],
                                  {"lines": [{"role": "A"}], "updated_by": KYLE}, WILL)
    assert got["updated_by"] == WILL
    assert store["library_assemblies"][0]["updated_by"] == WILL


def test_a_spoofed_name_on_its_own_is_not_even_a_write(store):
    """A PATCH whose only field is the forged one changes nothing at all, rather than landing an
    edit that renames the editor to whoever asked."""
    it = _mk_item(owner=KYLE)
    library.update_item(it["id"], {"unit_cost": 91.5}, WILL)
    stamped = library.get_item(it["id"])["updated_at"]
    got = library.update_item(it["id"], {"updated_by": "intruder@wetreadwell.com"}, None)
    assert got["updated_by"] == WILL and got["updated_at"] == stamped


# ── through the real endpoints ────────────────────────────────────────
def test_the_endpoint_stamps_the_signed_in_user_on_a_create(store):
    r = client.post("/api/library/items", json={"name": "OPF", "unit_cost": "$85.3827"})
    assert r.status_code == 200
    body = r.json()["item"]
    assert body["owner_email"] == SIGNED_IN and body["updated_by"] == SIGNED_IN


def test_the_endpoint_stamps_the_signed_in_user_on_an_edit(store):
    """The live path. Without `request` on this route the field would exist, be tested at the
    module, and still arrive empty from every real save."""
    it = _mk_item(owner=KYLE)
    r = client.patch("/api/library/items/%s" % it["id"], json={"unit_cost": "$91.50"})
    assert r.status_code == 200
    body = r.json()["item"]
    assert body["updated_by"] == SIGNED_IN, "the endpoint did not pass the caller's identity"
    assert body["owner_email"] == KYLE
    assert store["library_items"][0]["updated_by"] == SIGNED_IN


def test_the_endpoint_ignores_a_name_typed_into_the_body(store):
    """Two layers stop this — LibraryItemIn has no such field and validate_item drops unknown
    keys — and the request is the proof that both hold at once."""
    it = _mk_item(owner=KYLE)
    r = client.patch("/api/library/items/%s" % it["id"],
                     json={"unit_cost": "$91.50", "updated_by": "someone-else@wetreadwell.com",
                           "owner_email": "someone-else@wetreadwell.com"})
    assert r.status_code == 200
    assert r.json()["item"]["updated_by"] == SIGNED_IN
    assert r.json()["item"]["owner_email"] == KYLE


def test_the_assembly_endpoint_stamps_the_signed_in_user_on_a_line_edit(store):
    asm = _mk_asm(owner=KYLE)
    r = client.patch("/api/library/assemblies/%s" % asm["id"],
                     json={"lines": [{"item_id": "i1", "coverage": 275}],
                           "updated_by": "someone-else@wetreadwell.com"})
    assert r.status_code == 200
    body = r.json()["assembly"]
    assert body["updated_by"] == SIGNED_IN and body["owner_email"] == KYLE


def test_the_list_endpoints_return_both_names(store):
    """The tab reads the LIST, not one row. A shape that only carries the field on a single fetch
    would leave every column on screen blank."""
    _mk_item(owner=KYLE)
    _mk_asm(owner=KYLE)
    listed = client.get("/api/library/items").json()["items"]
    assert listed and listed[0]["updated_by"] == KYLE and listed[0]["owner_email"] == KYLE
    asms = client.get("/api/library/assemblies").json()["assemblies"]
    assert asms and asms[0]["updated_by"] == KYLE and asms[0]["owner_email"] == KYLE


# ── legacy rows, read-shaped rather than migrated ─────────────────────
def test_a_row_written_before_the_column_existed_reads_as_unknown(store):
    """Read-shaped, not migrated, exactly as buy_qty was. The tab shows "—" and no UPDATE goes
    anywhere near somebody's hand-typed row."""
    it = _mk_item(owner=KYLE)
    store["library_items"][0].pop("updated_by", None)
    assert library.get_item(it["id"])["updated_by"] == ""
    assert "updated_by" not in store["library_items"][0], "the stored row was rewritten"


def test_a_legacy_assembly_reads_as_unknown(store):
    asm = _mk_asm(owner=KYLE)
    store["library_assemblies"][0].pop("updated_by", None)
    assert library.get_assembly(asm["id"])["updated_by"] == ""
    assert "updated_by" not in store["library_assemblies"][0]


@pytest.mark.parametrize("shape,row", [
    (library._shape_item, {"id": "i1", "name": "OPF"}),
    (library._shape_assembly, {"id": "a1", "name": "MACRO Flake"}),
])
def test_the_shape_always_carries_the_key_even_with_the_column_absent(shape, row):
    """A KeyError on the frontend is a blank tab, not a blank cell. The key is always there; only
    its value is empty."""
    got = shape(row)
    assert "updated_by" in got and got["updated_by"] == ""
    assert "owner_email" in got and got["owner_email"] == ""


def test_a_legacy_row_still_names_its_editor_once_somebody_edits_it(store):
    """The dash is not permanent — the first real save fills it in."""
    it = _mk_item(owner=KYLE)
    store["library_items"][0].pop("updated_by", None)
    assert library.update_item(it["id"], {"notes": "checked"}, WILL)["updated_by"] == WILL


# ── not the price date ────────────────────────────────────────────────
def test_who_edited_it_is_not_the_price_date(store):
    """`cost_updated_at` is Hanz's PRICE-revision marker: "Date modified update should only trigger
    when cost is modified". Naming the editor of a spelling fix must not make a stale number look
    fresh, so the two stamps stay separate."""
    it = _mk_item(owner=KYLE, unit_cost=85.3827)
    library.update_item(it["id"], {"unit_cost": 91.5}, KYLE)
    priced = library.get_item(it["id"])["cost_updated_at"]
    assert priced
    got = library.update_item(it["id"], {"name": "OPF Primer"}, WILL)
    assert got["updated_by"] == WILL, "the spelling fix left no editor"
    assert got["cost_updated_at"] == priced, "an edit that was not a price change moved the price date"


def test_a_price_revision_records_both(store):
    it = _mk_item(owner=KYLE, unit_cost=85.3827)
    got = library.update_item(it["id"], {"unit_cost": 91.5}, WILL)
    assert got["updated_by"] == WILL and got["cost_updated_at"] == got["updated_at"]


# ── both databases ───────────────────────────────────────────────────
def test_both_schema_files_add_the_column_to_both_tables():
    """Prod is cloud Supabase; staging is its own Postgres. DDL applied to one and not the other
    surfaces as a 502 on whichever missed it, and PostgREST rejects a write naming a column it has
    no cache entry for. Additive `add column if not exists`, so it is safe to re-run."""
    for path in (BACKEND / "supabase_schema.sql", BACKEND / "staging" / "schema_pg.sql"):
        flat = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
        for table in ("library_items", "library_assemblies"):
            assert ("alter table public.%s add column if not exists updated_by text" % table) \
                in flat, "%s never adds updated_by to %s" % (path.name, table)
        # NULLABLE, and it must stay that way: a default naming the creator would have every
        # legacy row claim an edit that never happened.
        assert "updated_by text not null" not in flat, (
            "%s made updated_by NOT NULL — every pre-existing row would have to be given a name "
            "nobody recorded" % path.name)
        assert "updated_by text default" not in flat, (
            "%s gave updated_by a default; an unedited row would name somebody" % path.name)
        # ADDITIVE, not inside the original `create table`. Both live databases already hold these
        # tables, so `create table if not exists` is a no-op there — a column declared only inside
        # it would exist on a fresh volume and nowhere that matters.
        for table in ("library_items", "library_assemblies"):
            block = re.search(
                r"create table if not exists public\.%s \((.*?)\);" % table, flat)
            assert block, "%s no longer creates %s" % (path.name, table)
            assert "updated_by" not in block.group(1), (
                "%s declares updated_by inside create table %s, which is a no-op against a "
                "database that already has the table" % (path.name, table))
