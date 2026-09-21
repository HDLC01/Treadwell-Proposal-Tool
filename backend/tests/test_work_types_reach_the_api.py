"""The work-type scoping has to survive the REQUEST MODEL, not just the writer.

Hanz, 2026-09-21: "the filters in items in assemblies on the default items in assemblies. Is not
working." The Defaults tab shows five work-type chips over the takeoff list; every row in the
library carried `[]`, which appliesToWorkType reads as "applies to every work type", so all five
chips rendered one identical list.

THE FRONTEND WAS ONLY HALF OF IT. A writer was added to library.js the same day, and it still did
not work, because the field could never get past FastAPI:

    @app.patch("/api/library/items/{item_id}")
    def api_library_item_update(item_id, payload: LibraryItemIn, request):
        row = library.update_item(item_id, payload.model_dump(exclude_unset=True), ...)

`LibraryItemIn` did not declare `default_work_types`, and PYDANTIC DROPS AN UNDECLARED FIELD
WITHOUT A WORD. So the PATCH arrived carrying {"default_work_types": ["epoxy"]}, model_dump
returned {}, validate_item returned {}, update_item took its "nothing changed" early return, and
the route answered **200 OK** with the unchanged row. Every layer behaved correctly and the
feature was dead. Measured on staging: three PATCHes, all 200, all audit-logged, the column
still [] and `updated_at` never moving.

WHY THE OLD TESTS COULD NOT SEE IT. The Defaults-tab harness stubs the network — the split it
takes everywhere is "everything up to the request is the page's code, the socket is not" — so it
asserted the BODY the page would send, which was always correct. Nothing exercised the real
route. A request model is exactly the seam a stub hides.

The model docstrings say they are "loose on purpose ... so the rules can't drift between a
Pydantic model and the writer". That intent is right and the implementation did not carry it:
loose was never loose for a field the model had not been told about.

So there are two kinds of test here. The first three drive the REAL ROUTES and read the stored
row back. The last one is the class guard: it asserts that everything the validator accepts
survives its model, so the NEXT column added to library.py cannot repeat this.
"""
import pytest
from fastapi.testclient import TestClient

import library
import main

client = TestClient(main.app)


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"library_items": [], "library_assemblies": [], "library_labor": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(library, "get_client", lambda: fake)
    return st


# ── through the real routes ───────────────────────────────────────────────────
def test_patching_a_material_scopes_it_and_the_route_says_so(store):
    """The exact request the chip sends, against the real endpoint.

    Asserted on the STORED ROW and on the response body, not on the status code: the bug this
    covers answered 200 with a perfectly well-formed unchanged row, so a status assertion passes
    against it and so does anything that trusts the response without comparing it to the input.

    Mutation: delete `default_work_types` from LibraryItemIn. This goes red; nothing else does."""
    it = library.create_item({"name": "Gyp primer", "unit": "Gallon", "unit_cost": 50}, None)
    assert it["default_work_types"] == [], "a new material should start applying everywhere"

    r = client.patch("/api/library/items/%s" % it["id"], json={"default_work_types": ["gyp"]})
    assert r.status_code == 200, r.text
    assert r.json()["item"]["default_work_types"] == ["gyp"], (
        "the route answered 200 with the field unchanged -- which is exactly how this failed "
        "silently for the whole time the chips were on screen")
    assert library.get_item(it["id"])["default_work_types"] == ["gyp"], (
        "the response carried the new scope but the stored row did not")


def test_patching_an_assembly_scopes_it_too(store):
    """Same seam, second model. The Defaults tab draws the chips on assembly rows as well, so a
    fix that named the field on one model would leave the other dead with this file still green
    if it only covered materials."""
    asm = library.create_assembly({"name": "Polish 800", "unit": "SF"}, None)
    r = client.patch("/api/library/assemblies/%s" % asm["id"],
                     json={"default_work_types": ["polish", "seal"]})
    assert r.status_code == 200, r.text
    assert library.get_assembly(asm["id"])["default_work_types"] == ["polish", "seal"]


def test_emptying_the_list_returns_a_row_to_every_work_type(store):
    """The other direction, and the one that could strand a row if it did not work.

    `[]` is not "applies to nothing" -- it is what appliesToWorkType has always read as every
    work type, and what every row predating the column relies on. So a row scoped into a corner
    has to be able to come back, and `[]` has to survive `exclude_unset=True` as a real value
    rather than being mistaken for "not sent"."""
    it = library.create_item({"name": "Densifier", "unit": "Pail",
                              "default_work_types": ["gyp"]}, None)
    assert library.get_item(it["id"])["default_work_types"] == ["gyp"]

    r = client.patch("/api/library/items/%s" % it["id"], json={"default_work_types": []})
    assert r.status_code == 200, r.text
    assert library.get_item(it["id"])["default_work_types"] == [], (
        "an empty list did not reach the writer, so a scoped row can never be un-scoped")


def test_an_off_list_work_type_is_refused_rather_than_dropped(store):
    """A 400, not a silent []. A work type nothing looks up is a default that never applies, and
    on screen that is indistinguishable from one switched off -- which is the worst way for a
    pricing default to fail, and the reason _coerce_work_types raises instead of filtering."""
    it = library.create_item({"name": "OPF", "unit": "Gallon"}, None)
    r = client.patch("/api/library/items/%s" % it["id"],
                     json={"default_work_types": ["terrazzo"]})
    assert r.status_code == 400, (
        "an unknown work type was accepted; it stores as something no tab reads, so the row "
        "silently never appears anywhere")
    assert "terrazzo" in r.text
    assert library.get_item(it["id"])["default_work_types"] == [], "the refusal still wrote"


# ── the class guard, so the next column cannot repeat this ────────────────────
# ONE PROBE PER FIELD, because the validators coerce and a single value cannot satisfy all of
# them. The point is not what the value becomes -- it is whether the key SURVIVES the model at
# all, which is the only thing that failed.
PROBES = {
    "name": "Probe", "category": "Epoxy", "divisions": ["Epoxy"], "unit": "Gallon",
    "buy_qty": "5", "unit_cost": "85.38", "coverage": "275", "sku": "SKU-1",
    "vendor": "Acme", "notes": "a note", "favorite": True,
    "description": "a system", "lines": [], "expected_updated_at": "2026-01-01T00:00:00+00:00",
    "rate": "33", "guys_auto": True, "sort": "0",
    "default_work_types": ["epoxy"],
}


@pytest.mark.parametrize("model_name,writable", [
    ("LibraryItemIn", library.ITEM_WRITABLE),
    ("LibraryAssemblyIn", library.ASM_WRITABLE),
    ("LibraryLaborIn", library.LABOR_WRITABLE),
])
def test_every_writable_field_survives_its_request_model(model_name, writable):
    """THE INVARIANT THAT WAS BROKEN, stated so it cannot break again.

    library.py's own comment on these tuples says "an added column is safe by default and has to
    be opted IN to be writable". True of the writer, and it says nothing about the request model
    two layers up -- which is where the opt-in was missed. A name on a WRITABLE tuple that the
    model does not declare is a field the API accepts, acknowledges with a 200, and discards.

    Executed against the real model class, so this reads the code that runs rather than a list
    somebody remembered to update."""
    model = getattr(main, model_name)
    missing = []
    for field in writable:
        probe = PROBES.get(field, "probe")
        dumped = model(**{field: probe}).model_dump(exclude_unset=True)
        if field not in dumped:
            missing.append(field)
    assert not missing, (
        "%s silently discards %s -- library.py will accept %s from a script but the API never "
        "will, and the route still answers 200" % (model_name, ", ".join(missing),
                                                   ", ".join(missing)))


def test_the_guard_above_would_actually_have_caught_it():
    """NOT VACUOUS, proven rather than asserted.

    A model built without the field must fail the same check the real ones pass, or the
    parametrised test above is a green light that cannot turn red and the original bug would
    ship again behind it."""
    from typing import Any, Optional

    from pydantic import BaseModel

    class WithoutTheField(BaseModel):
        name: Optional[str] = None
        unit_cost: Optional[Any] = None

    dumped = WithoutTheField(**{"default_work_types": ["epoxy"]}).model_dump(exclude_unset=True)
    assert "default_work_types" not in dumped, (
        "Pydantic kept an undeclared field, so the failure mode this whole file documents "
        "cannot occur and these tests are guarding nothing -- check the model config")
    # …and the real one keeps it, which is the fix.
    assert "default_work_types" in main.LibraryItemIn(
        **{"default_work_types": ["epoxy"]}).model_dump(exclude_unset=True)
