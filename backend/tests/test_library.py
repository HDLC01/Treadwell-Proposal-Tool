"""Item Library — the data layer and its endpoints.

Kyle and Will want to compose their own systems instead of the fixed ones baked into the
estimate sheet. `library.py` stores the materials and the assemblies; the arithmetic lives in
`frontend/js/library-core.js` and is pinned separately in test_library_core_js.py.

What these tests are actually protecting:

  * **Pasted numbers.** Every cost and coverage in this library will be pasted out of a
    spreadsheet, arriving as "$85.3827" and "2,875". Refusing those teaches people to retype
    them, which is how a digit gets dropped from a price.
  * **A half-built line is normal.** Somebody adds a row, then picks the material. Refusing the
    whole save because one line is incomplete would make the editor unusable, so an empty line
    is dropped rather than rejected.
  * **Zero coverage is not a coverage.** One unit covering nothing prices every job as infinite
    material, so it is stored as "not set" instead of accepted.
  * **Deleting a material leaves assemblies alone.** `item_id` is deliberately not a foreign
    key. A delete must not silently rewrite somebody else's assembly, and an FK would instead
    refuse the delete forever. The line goes visibly broken and the estimator repoints it.
  * **A soft delete really hides the row**, and a write to a deleted row 404s rather than
    reporting a cheerful success to nothing.

Runs against the in-memory Supabase fake, like test_archive.py — conftest refuses to let the
suite reach the production data store.
"""
import pytest
from fastapi.testclient import TestClient

import library
import main

client = TestClient(main.app)


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"library_items": [], "library_assemblies": [], "library_vendors": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(library, "get_client", lambda: fake)
    return st


def _mk_item(**kw):
    body = {"name": "OPF", "unit": "Gal", "unit_cost": 85.3827, "coverage": 275}
    body.update(kw)
    return library.create_item(body, "hanz@wetreadwell.com")


# ── items: validation ─────────────────────────────────────────────────
def test_an_item_needs_a_name():
    with pytest.raises(library.ValidationError):
        library.validate_item({"unit_cost": 10})


def test_a_name_is_tidied_not_rejected():
    got = library.validate_item({"name": "  Armor   Top   Satin  "})
    assert got["name"] == "Armor Top Satin"


@pytest.mark.parametrize("raw,expect", [
    (85.3827, 85.3827), ("85.3827", 85.3827), ("$85.3827", 85.3827),
    ("$1,200.50", 1200.5), (" 275 ", 275.0), ("", None), (None, None), (0, 0.0),
])
def test_costs_survive_being_pasted_from_a_spreadsheet(raw, expect):
    assert library.validate_item({"name": "x", "unit_cost": raw})["unit_cost"] == expect


@pytest.mark.parametrize("bad", ["abc", "12abc", True, float("nan"), float("inf")])
def test_a_cost_that_is_not_a_number_is_refused_with_a_readable_message(bad):
    with pytest.raises(library.ValidationError) as e:
        library.validate_item({"name": "x", "unit_cost": bad})
    assert "number" in str(e.value).lower()


def test_a_negative_cost_is_refused():
    with pytest.raises(library.ValidationError) as e:
        library.validate_item({"name": "x", "unit_cost": -5})
    assert "negative" in str(e.value).lower()


def test_an_implausible_cost_is_refused_rather_than_stored():
    with pytest.raises(library.ValidationError):
        library.validate_item({"name": "x", "unit_cost": 99999999})


def test_zero_coverage_is_stored_as_not_set():
    """One unit covering nothing would price every job as infinite material. Treated as
    "nobody has filled this in" rather than accepted as a number."""
    assert library.validate_item({"name": "x", "coverage": 0})["coverage"] is None
    assert library.validate_item({"name": "x", "coverage": ""})["coverage"] is None


def test_the_purchase_unit_is_freeform_with_a_sensible_default():
    """The page offers Gallon / Kit / Bag (Hanz, 2026-08-15), but the column stays freeform: Kyle's
    earlier rows say Gal, Pint, Quart, Each and Roll, and the next product will use something
    nobody has thought of. A closed list would block the purchase rather than the typo."""
    assert library.validate_item({"name": "x"})["unit"] == "Gallon"
    assert library.validate_item({"name": "x", "unit": "Pail"})["unit"] == "Pail"
    # A legacy abbreviation is neither rewritten nor refused.
    assert library.validate_item({"name": "x", "unit": "Gal"})["unit"] == "Gal"


def test_unknown_keys_are_ignored_not_stored():
    """An unknown key is a client bug. Persisting it makes the row shape unpredictable for
    every later reader."""
    got = library.validate_item({"name": "x", "nonsense": 1, "deleted_at": "now"})
    assert "nonsense" not in got and "deleted_at" not in got


def test_a_partial_update_only_touches_what_it_names():
    got = library.validate_item({"unit_cost": 12}, partial=True)
    assert got == {"unit_cost": 12.0}, "a partial patch must not blank the other columns"


# ── items: round trip ─────────────────────────────────────────────────
def test_creating_and_listing_an_item(store):
    row = _mk_item()
    assert row["name"] == "OPF" and row["unit_cost"] == 85.3827
    listed = library.list_items()
    assert [r["id"] for r in listed] == [row["id"]]


def test_numbers_come_back_as_numbers_not_strings(store):
    """PostgREST returns numerics as strings. The page does arithmetic with these, so the
    coercion belongs here rather than in every caller."""
    _mk_item()
    store["library_items"][0]["unit_cost"] = "85.3827"     # what PostgREST actually hands back
    store["library_items"][0]["coverage"] = "275.000"
    got = library.list_items()[0]
    assert got["unit_cost"] == 85.3827 and got["coverage"] == 275.0


def test_updating_a_cost(store):
    row = _mk_item()
    got = library.update_item(row["id"], {"unit_cost": "$90.00"})
    assert got["unit_cost"] == 90.0
    assert library.list_items()[0]["unit_cost"] == 90.0


def test_a_soft_deleted_item_disappears_from_the_list_but_keeps_its_row(store):
    row = _mk_item()
    assert library.delete_item(row["id"]) is True
    assert library.list_items() == []
    assert library.get_item(row["id"]) is None
    assert store["library_items"][0]["deleted_at"], "the row should be kept, not destroyed"


def test_updating_a_deleted_item_reports_gone_rather_than_success(store):
    row = _mk_item()
    library.delete_item(row["id"])
    assert library.update_item(row["id"], {"unit_cost": 1}) is None


def test_updating_a_deleted_item_does_not_write_to_it(store):
    """Returning None is not enough on its own.

    Without the existence check the patch still lands on the soft-deleted row while the caller
    is told the record is gone — because `get_item` filters deleted rows and so reports None
    either way. The row would then carry edits nobody made deliberately if it were ever
    restored, and the 404 response would have performed a write. Verified by removing the
    check: the test above stayed green, this one does not."""
    row = _mk_item()
    library.delete_item(row["id"])
    library.update_item(row["id"], {"unit_cost": 999})
    stored = store["library_items"][0]
    assert float(stored["unit_cost"]) == 85.3827, "a deleted row was modified"


def test_deleting_twice_is_not_a_success_the_second_time(store):
    row = _mk_item()
    assert library.delete_item(row["id"]) is True
    assert library.delete_item(row["id"]) is False


# ── assemblies: lines ─────────────────────────────────────────────────
def test_an_assembly_needs_a_name():
    with pytest.raises(library.ValidationError):
        library.validate_assembly({"lines": []})


def test_lines_keep_their_order():
    """The order IS the system: primer, body coat, top coat. A reorder would change what gets
    read back as the build-up."""
    got = library.validate_assembly({"name": "x", "lines": [
        {"role": "1st BC", "item_id": "a"}, {"role": "Grout", "item_id": "b"},
        {"role": "Top", "item_id": "c"}]})
    assert [l["role"] for l in got["lines"]] == ["1st BC", "Grout", "Top"]


def test_an_empty_line_is_dropped_rather_than_failing_the_save():
    """A half-built line is the normal state of this screen: add a row, then pick the material.
    Failing the save would make the editor unusable."""
    got = library.validate_assembly({"name": "x", "lines": [
        {"role": "Top Coat", "item_id": "a"}, {"role": "", "item_id": ""}, {}]})
    assert len(got["lines"]) == 1


def test_a_line_with_a_role_but_no_material_yet_is_kept():
    """Somebody typed the role first. Dropping it would delete their work as they type."""
    got = library.validate_assembly({"name": "x", "lines": [{"role": "Top Coat"}]})
    assert len(got["lines"]) == 1
    assert got["lines"][0]["item_id"] is None


def test_a_lines_coverage_is_read_and_zero_becomes_unset():
    got = library.validate_assembly({"name": "x", "lines": [
        {"item_id": "a", "coverage": "775"}, {"item_id": "b", "coverage": 0}]})
    assert got["lines"][0]["coverage"] == 775.0
    assert got["lines"][1]["coverage"] is None


def test_too_many_lines_are_capped_not_rejected():
    got = library.validate_assembly({"name": "x", "lines": [
        {"item_id": "a"} for _ in range(500)]})
    assert len(got["lines"]) == library._MAX_LINES


@pytest.mark.parametrize("bad", ["nope", 5, {"a": 1}])
def test_lines_that_are_not_a_list_are_refused_readably(bad):
    with pytest.raises(library.ValidationError):
        library.validate_assembly({"name": "x", "lines": bad})


def test_garbage_inside_the_lines_list_is_skipped(store):
    got = library.validate_assembly({"name": "x", "lines": [None, "nope", 7,
                                                            {"item_id": "a", "role": "Top"}]})
    assert len(got["lines"]) == 1


def test_creating_and_reading_back_an_assembly(store):
    it = _mk_item()
    row = library.create_assembly({"name": "MACRO Flake", "lines": [
        {"role": "1st BC", "item_id": it["id"], "coverage": 275}]}, "hanz@wetreadwell.com")
    got = library.get_assembly(row["id"])
    assert got["name"] == "MACRO Flake"
    assert got["lines"][0]["item_id"] == it["id"]
    assert got["lines"][0]["coverage"] == 275.0


def test_an_assembly_with_no_lines_column_reads_as_empty(store):
    """A row written before `lines` existed, or a null, must not crash the list."""
    library.create_assembly({"name": "x"}, None)
    store["library_assemblies"][0]["lines"] = None
    assert library.list_assemblies()[0]["lines"] == []


# ── the referential edge that has no foreign key ──────────────────────
def test_deleting_a_material_leaves_the_assembly_alone(store):
    """THE deliberate design choice. `item_id` is not an FK: a delete must not rewrite somebody
    else's assembly, and an FK would refuse the delete forever. The line survives, pointing at
    a material that is gone, and the pricing layer reports it as broken."""
    it = _mk_item()
    asm = library.create_assembly({"name": "Flake", "lines": [
        {"role": "Top Coat", "item_id": it["id"], "coverage": 775}]}, None)
    library.delete_item(it["id"])
    got = library.get_assembly(asm["id"])
    assert len(got["lines"]) == 1, "the line was silently removed from someone's assembly"
    assert got["lines"][0]["item_id"] == it["id"], "the reference was rewritten"
    assert library.get_item(it["id"]) is None


def test_deleting_an_assembly_does_not_touch_its_materials(store):
    it = _mk_item()
    asm = library.create_assembly({"name": "Flake", "lines": [
        {"item_id": it["id"], "role": "Top"}]}, None)
    library.delete_assembly(asm["id"])
    assert library.list_assemblies() == []
    assert library.get_item(it["id"]) is not None


# ── endpoints ─────────────────────────────────────────────────────────
def test_the_item_endpoints_round_trip(store):
    r = client.post("/api/library/items", json={"name": "OPF", "unit_cost": "$85.3827"})
    assert r.status_code == 200, r.text
    item_id = r.json()["item"]["id"]
    assert r.json()["item"]["unit_cost"] == 85.3827

    r = client.get("/api/library/items")
    assert [i["id"] for i in r.json()["items"]] == [item_id]

    r = client.patch("/api/library/items/%s" % item_id, json={"coverage": "275"})
    assert r.status_code == 200 and r.json()["item"]["coverage"] == 275.0

    r = client.delete("/api/library/items/%s" % item_id)
    assert r.status_code == 200
    assert client.get("/api/library/items").json()["items"] == []


def test_the_assembly_endpoints_round_trip(store):
    r = client.post("/api/library/assemblies", json={"name": "MACRO Flake"})
    assert r.status_code == 200, r.text
    aid = r.json()["assembly"]["id"]

    r = client.patch("/api/library/assemblies/%s" % aid,
                     json={"lines": [{"role": "Top", "item_id": "x", "coverage": "775"}]})
    assert r.status_code == 200
    assert r.json()["assembly"]["lines"][0]["coverage"] == 775.0

    assert client.delete("/api/library/assemblies/%s" % aid).status_code == 200
    assert client.get("/api/library/assemblies").json()["assemblies"] == []


def test_a_bad_payload_is_a_400_with_a_message_not_a_500(store):
    r = client.post("/api/library/items", json={"name": ""})
    assert r.status_code == 400, r.text
    assert "name" in r.json()["detail"].lower()

    r = client.post("/api/library/items", json={"name": "x", "unit_cost": "abc"})
    assert r.status_code == 400
    assert "number" in r.json()["detail"].lower()


def test_writing_to_something_that_is_gone_is_a_404(store):
    assert client.patch("/api/library/items/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/library/items/nope").status_code == 404
    assert client.patch("/api/library/assemblies/nope", json={"name": "x"}).status_code == 404
    assert client.delete("/api/library/assemblies/nope").status_code == 404


@pytest.mark.parametrize("payload", [
    {}, {"name": None}, {"name": "x", "lines": "nope"}, {"name": "x", "coverage": {}},
    {"name": "x", "unit_cost": []}, {"name": "x", "lines": [{"coverage": "abc"}]},
])
def test_hostile_payloads_never_500(store, payload):
    for path in ("/api/library/items", "/api/library/assemblies"):
        r = client.post(path, json=payload)
        assert r.status_code in (200, 400, 422), (path, payload, r.status_code, r.text)


# ── the page is wired up ──────────────────────────────────────────────
def test_the_page_loads_the_pricing_core_before_itself():
    """`var L = window.TWLib` runs at parse time, so a missing or late script tag is an
    immediate TypeError and the whole page fails to initialise."""
    import pathlib
    html = (pathlib.Path(__file__).resolve().parents[2]
            / "frontend" / "library.html").read_text(encoding="utf-8")
    i, j = html.find("library-core.js"), html.find("/js/library.js")
    assert i != -1 and j != -1, "library.html does not load both scripts"
    assert i < j, "the pricing core must load BEFORE the page script"
    assert "auth.js" in html and "shared.js" in html


def test_every_request_waits_for_the_token_in_one_place():
    """The Bid Calendar shipped a 401 that hid the estimator's own entries because `load()`
    waited for the bearer token and its sibling did not. One helper, one await."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "frontend" / "js" / "library.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.split("\n") if not l.strip().startswith("//"))
    # Nothing may call fetch() directly and skip the wait.
    assert code.count("fetch(") == 1, "a fetch outside the api() helper would skip the token wait"
    # The wait belongs to the REQUEST helper, not to whichever loader remembered it. Sliced from
    # `var api =` to its closing brace, so the second await added on 2026-08-15 — load() resolving
    # the caller's admin role before the first paint, which is not a request — cannot satisfy this.
    body = code[code.index("var api = async function"):]
    body = body[:body.index("\n  };")]
    assert body.count("await window.TWAuth.ready") == 1, \
        "api() no longer waits for the bearer token"


def test_pending_edits_are_merged_not_replaced():
    """Every edit PATCHes a single field, debounced per record. If the pending body is REPLACED
    instead of merged, editing a material's name and then its cost inside the debounce window
    sends only the cost and the name is silently lost.

    That is not hypothetical — it shipped. On staging I typed three materials with a name, unit,
    cost and coverage each, reloaded, and found them all still called "New material" with one of
    three costs saved. Typing a name then tabbing straight to a price is the normal way to fill
    a row, so it would have happened to Kyle immediately."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "frontend" / "js" / "library.js").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.split("\n") if not l.strip().startswith("//"))
    assert "pendingPatch[key] = Object.assign(pendingPatch[key] || {}, body)" in code, (
        "patchSoon does not merge pending fields; a multi-field edit will lose all but the last")
    # And the buffer must be cleared when the request actually goes out, or a later edit would
    # re-send fields that were already saved.
    assert "delete pendingPatch[key]" in code
    assert "JSON.stringify(payload)" in code, "the merged payload is not what gets sent"


def test_the_sidebar_has_one_entry_and_no_duplicate_glyph():
    import pathlib
    import re
    src = (pathlib.Path(__file__).resolve().parents[2]
           / "frontend" / "auth.js").read_text(encoding="utf-8")
    assert 'navItem("/library.html"' in src
    glyphs = re.findall(r'navItem\("[^"]+", "([^"]+)"', src)
    assert len(glyphs) == len(set(glyphs)), "two sidebar items share a glyph: %s" % glyphs


def test_both_schema_files_declare_the_tables():
    """Staging runs its own Postgres, prod runs cloud Supabase. A table added to one and not
    the other reads 200 and writes a bare 404 on the environment that missed it."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    for path in (root / "supabase_schema.sql", root / "staging" / "schema_pg.sql"):
        sql = path.read_text(encoding="utf-8")
        for table in ("library_items", "library_assemblies"):
            assert ("create table if not exists public.%s" % table) in sql, (path.name, table)


def test_the_page_and_the_sidebar_both_say_it_is_a_beta():
    """Hanz asked for it labelled. Two places, because they answer different moments: the
    sidebar tells you before you click, and the page tells you while you are typing numbers
    into it three weeks later."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "frontend"
    html = (root / "library.html").read_text(encoding="utf-8")
    auth = (root / "auth.js").read_text(encoding="utf-8")
    assert 'class="beta"' in html and "Beta test" in html
    assert ".beta {" in html, "the marker has no style and would inherit body text"
    assert 'navItem("/library.html", "\U0001f9f1", "Items and Assemblies", "BETA")' in auth
    assert ".tw-nav-tag{" in auth, "the sidebar tag has no style"


# ── two people editing one assembly ───────────────────────────────────────────
# From the adversarial audit. Every line change PATCHes the WHOLE lines array, from a snapshot the
# page fetched once at load. Two editors therefore overwrite each other completely, in silence:
# the second save replaces the first person's lines with a state that predates them, neither
# screen shows anything wrong, and soft-delete does not help because it protects rows, not the
# contents of one.
def test_a_write_against_a_stale_version_is_refused(store):
    asm = library.create_assembly({"name": "MACRO Flake"}, "hanz@wetreadwell.com")
    library.update_assembly(asm["id"], {"lines": [{"role": "1st BC"}]})     # the other person
    with pytest.raises(library.StaleWrite) as e:
        library.update_assembly(asm["id"], {
            "lines": [], "expected_updated_at": asm["updated_at"]})          # our stale snapshot
    assert e.value.current["lines"], "the refusal did not carry the version that won"


def test_the_refused_write_did_not_land(store):
    """The point. A refusal that still writes is worse than no check at all."""
    asm = library.create_assembly({"name": "MACRO Flake"}, "hanz@wetreadwell.com")
    library.update_assembly(asm["id"], {"lines": [{"role": "Top Coat"}]})
    try:
        library.update_assembly(asm["id"], {"lines": [], "expected_updated_at": asm["updated_at"]})
    except library.StaleWrite:
        pass
    assert library.get_assembly(asm["id"])["lines"], "the other person's lines were destroyed"


def test_a_write_with_the_current_version_goes_through(store):
    asm = library.create_assembly({"name": "MACRO Flake"}, "hanz@wetreadwell.com")
    got = library.update_assembly(asm["id"], {
        "lines": [{"role": "Grout"}], "expected_updated_at": asm["updated_at"]})
    assert got and len(got["lines"]) == 1


def test_a_caller_that_declares_no_version_is_not_forced_to(store):
    """curl, an import script, or anything that is not the editor. Only the editor has the
    conflict, because only it holds a snapshot."""
    asm = library.create_assembly({"name": "MACRO Flake"}, "hanz@wetreadwell.com")
    library.update_assembly(asm["id"], {"lines": [{"role": "A"}]})
    got = library.update_assembly(asm["id"], {"lines": [{"role": "B"}]})
    assert len(got["lines"]) == 1 and got["lines"][0]["role"] == "B"


def test_the_endpoint_answers_409_with_the_version_that_won(store):
    asm = library.create_assembly({"name": "MACRO Flake"}, "hanz@wetreadwell.com")
    library.update_assembly(asm["id"], {"lines": [{"role": "1st BC"}]})
    r = client.patch("/api/library/assemblies/" + asm["id"],
                     json={"lines": [], "expected_updated_at": asm["updated_at"]})
    assert r.status_code == 409
    body = r.json()
    assert body["ok"] is False
    assert body["assembly"]["lines"], "the page cannot show what it would have destroyed"
    assert "changed" in body["error"].lower()
