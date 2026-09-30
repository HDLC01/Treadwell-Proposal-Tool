"""Default labor lines — the table behind Library → Defaults → "+ Add a labor line".

The button shipped DEAD, on purpose: nothing stored a custom labor line, so `renderDefaultLabor()`
drew exactly one hardcoded row out of `TWPolishBid.travelSeed()` and the Add button had nowhere to
put a second one. Hanz reported it twice on staging. `library_labor` is where a custom line now
lives, and this file is the backend half of it.

WHAT THESE TESTS ARE ACTUALLY DEFENDING:

  * **The table does not exist on production.** It was applied to staging on 2026-09-17; prod gets
    it when Hanz promotes. So a GET has to answer "no custom labor lines" rather than 500 — on
    prod today, and on any box where the DDL has not run. Without that, the Library page goes down
    the moment this reaches prod, over a section nobody there has used yet. That is the single
    most valuable test in this file, and it is the one that needs a store that RAISES rather than
    a store that is merely empty.

  * **A write must NOT degrade the same way.** A read of an absent table is honestly empty; a
    write that quietly does nothing tells an admin they saved a rate they did not save, and they
    find out when a bid is short. The asymmetry is deliberate, so it is pinned.

  * **`unit` is the one closed list in this module.** The estimate multiplies a rate by HOURS or
    by DAYS and has no third multiplier — a line saying "weeks" would price as nothing while
    still showing the rate somebody typed. Everything else here (divisions, item units, assembly
    units) is offered-not-enforced, so the exception has to be held down.

  * **Travel is ONE RESERVED ROW in this table, seeded by the schema and by nothing else.** It
    stopped being a literal on 2026-09-19 ("again this too how can we edit this?" -- Hanz, on the
    BUILT IN chip the Defaults tab drew beside it). Two rules hold it down and both are tested
    here: the row is named by the SQL, never by the API (`LibraryLaborIn` has no `id` and
    `create_labor` mints a uuid, so no caller can make a second row claiming the reserved id),
    and an absent or soft-deleted row falls back to `travelSeed()`'s own $33.00/hr rather than
    taking Travel off anybody's estimate. Nothing seeds the table in Python: `_ref_defaults` is
    empty for it, because a Python-side default would be a second statement of Kyle's rate.

  * **The row shape is a contract.** Three tracks were built against it at once. The exact key set
    is pinned so the frontend's one mapping at the seam cannot be fed a key that is not there.

Runs against the in-memory Supabase fake, like test_library.py — conftest refuses to let the suite
reach the production data store.
"""
import pytest
from fastapi.testclient import TestClient

import library
import main
import profiles

client = TestClient(main.app)


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"library_labor": []}
    fake = fake_supabase(st)
    monkeypatch.setattr(library, "get_client", lambda: fake)
    return st


@pytest.fixture()
def as_admin(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "a1", "email": e, "role": "admin"})


@pytest.fixture()
def as_user(monkeypatch):
    monkeypatch.setattr(main, "_SUPER_ADMIN_EMAIL", "somebody-else@wetreadwell.com")
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": e, "role": "user"})


def _mk(**kw):
    body = {"name": "Mobilization", "rate": 45, "unit": "hours"}
    body.update(kw)
    return library.create_labor(body, "hanz@wetreadwell.com")


# ── the table is not there yet ────────────────────────────────────────
class _SchemaCacheMiss(Exception):
    """What PostgREST answers when the relation is not in its schema cache.

    Written out by hand rather than imported from postgrest: the point of the guard is that
    `list_labor` does NOT care which class arrives — an absent table, an unconfigured client and a
    network blip all mean the same thing to the page — so pinning it to the real class would be
    pinning the wrong thing."""


class _TableMissingClient:
    """A store where `library_labor` has not been created. Every other table still works.

    Deliberately NOT "the fake store with no rows in it": an empty table and an absent table are
    different failures, and the fake's `setdefault` turns the second into the first. That is
    exactly why the dead button shipped green — the harness could not tell a missing thing from an
    empty one."""

    def __init__(self, inner):
        self.inner = inner
        self.store = inner.store
        self.captures = inner.captures

    def table(self, name):
        if name == library.LABOR:
            return _ExplodingTable(name)
        return self.inner.table(name)


class _ExplodingTable:
    def __init__(self, name):
        self.name = name

    def __getattr__(self, _attr):
        return lambda *a, **k: self

    def execute(self):
        raise _SchemaCacheMiss(
            "{'code': 'PGRST205', 'message': \"Could not find the table "
            "'public.%s' in the schema cache\"}" % self.name)


@pytest.fixture()
def table_missing(fake_supabase, monkeypatch):
    fake = _TableMissingClient(fake_supabase({}))
    monkeypatch.setattr(library, "get_client", lambda: fake)
    return fake


def test_a_missing_table_reads_as_no_custom_lines_not_a_500(table_missing):
    """PRODUCTION HAS NO `library_labor` TABLE. This is the defect that would take the Library
    page down the moment this reaches prod, so it is asserted through the endpoint rather than
    the function: a 500 here is a blank tab for Kyle over a feature he has not used."""
    r = client.get("/api/library/labor")
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "labor": []}


def test_the_missing_table_degrades_at_the_data_layer_too(table_missing):
    """Not only at the route. Any later reader — the estimate, a digest — gets the same empty
    list rather than an exception it would have to know to catch."""
    assert library.list_labor() == []


def test_a_write_does_not_degrade_when_the_table_is_missing(table_missing):
    """The asymmetry with the read is the point of both. A create that silently does nothing
    tells an admin they saved a rate they did not save."""
    with pytest.raises(_SchemaCacheMiss):
        library.create_labor({"name": "Mobilization", "rate": 45}, None)


# ── validation ────────────────────────────────────────────────────────
def test_a_labor_line_needs_a_name():
    with pytest.raises(library.ValidationError) as e:
        library.validate_labor({"rate": 45})
    assert "name" in str(e.value).lower()


def test_a_blank_name_is_refused_not_stored_as_untitled():
    for blank in ("", "   ", None):
        with pytest.raises(library.ValidationError):
            library.validate_labor({"name": blank, "rate": 1})


def test_a_name_is_tidied_not_rejected():
    assert library.validate_labor({"name": "  Night   shift  "})["name"] == "Night shift"


@pytest.mark.parametrize("raw,expect", [
    (45, 45.0), ("45", 45.0), ("$45.50", 45.5), (" 33 ", 33.0), (0, 0.0),
])
def test_a_rate_survives_being_typed_or_pasted(raw, expect):
    assert library.validate_labor({"name": "x", "rate": raw})["rate"] == expect


def test_a_blank_rate_is_zero_not_missing():
    """Unlike an item's unit_cost. A rate stored as "not set" would let a line price a bid at
    nothing while looking complete on screen; zero shows as zero."""
    assert library.validate_labor({"name": "x", "rate": ""})["rate"] == 0.0
    assert library.validate_labor({"name": "x"})["rate"] == 0.0


def test_a_negative_rate_is_refused_with_a_readable_message():
    with pytest.raises(library.ValidationError) as e:
        library.validate_labor({"name": "x", "rate": -5})
    assert "negative" in str(e.value).lower()


@pytest.mark.parametrize("bad", ["abc", "12abc", True, float("nan"), float("inf")])
def test_a_rate_that_is_not_a_number_is_refused(bad):
    with pytest.raises(library.ValidationError) as e:
        library.validate_labor({"name": "x", "rate": bad})
    assert "number" in str(e.value).lower()


def test_an_implausibly_large_rate_is_refused_rather_than_stored():
    """$1M an hour is a typo, and numeric(10,2) would refuse it at the store with a 500 instead
    of a sentence."""
    with pytest.raises(library.ValidationError) as e:
        library.validate_labor({"name": "x", "rate": 99999999})
    assert "large" in str(e.value).lower()


@pytest.mark.parametrize("unit", ["hours", "days", "Hours", "DAYS"])
def test_the_two_real_units_are_accepted_whatever_the_shift_key_did(unit):
    assert library.validate_labor({"name": "x", "unit": unit})["unit"] == unit.lower()


@pytest.mark.parametrize("unit", ["weeks", "SF", "hour", "each", "hrs"])
def test_any_other_unit_is_refused(unit):
    """The one CLOSED list in this module. The estimate multiplies a rate by hours or by days and
    has no third multiplier — a "weeks" line would price as nothing, on a screen still showing
    the rate somebody typed."""
    with pytest.raises(library.ValidationError) as e:
        library.validate_labor({"name": "x", "unit": unit})
    assert "hours" in str(e.value).lower() and "days" in str(e.value).lower()


def test_an_absent_or_blank_unit_takes_the_default_rather_than_erroring():
    """A client clearing a field is asking for the column default, not proposing a third unit."""
    assert library.validate_labor({"name": "x"})["unit"] == "hours"
    assert library.validate_labor({"name": "x", "unit": ""})["unit"] == "hours"


def test_guys_auto_is_coerced_not_validated():
    assert library.validate_labor({"name": "x", "guys_auto": True})["guys_auto"] is True
    assert library.validate_labor({"name": "x", "guys_auto": "yes"})["guys_auto"] is True
    assert library.validate_labor({"name": "x"})["guys_auto"] is False


def test_sort_is_a_whole_number():
    assert library.validate_labor({"name": "x", "sort": "2"})["sort"] == 2
    assert library.validate_labor({"name": "x", "sort": 2.7})["sort"] == 2
    assert library.validate_labor({"name": "x"})["sort"] == 0
    with pytest.raises(library.ValidationError):
        library.validate_labor({"name": "x", "sort": -1})


def test_unknown_keys_are_ignored_not_stored():
    got = library.validate_labor({"name": "x", "nonsense": 1, "deleted_at": "now",
                                  "owner_email": "someone-else@example.com"})
    assert "nonsense" not in got and "deleted_at" not in got and "owner_email" not in got


def test_a_partial_update_only_touches_what_it_names():
    got = library.validate_labor({"rate": 12}, partial=True)
    assert got == {"rate": 12.0}, "a partial patch must not blank the other columns"


# ── round trip ────────────────────────────────────────────────────────
def test_creating_and_listing(store):
    row = _mk()
    assert row["name"] == "Mobilization" and row["rate"] == 45.0
    assert [r["id"] for r in library.list_labor()] == [row["id"]]


def test_the_row_shape_is_exactly_what_the_other_tracks_were_built_against(store):
    """Three tracks were built against this at once, and the frontend maps it at the seam into
    the estimate's own labor-row shape. A key that is not here is a `undefined` on a bid.

    `favorite` joined the set 2026-09-24, the same day the Labor tab did — see
    test_creating_defaults_favorite_to_false and test_favorite_round_trips below for what it
    actually does; this one only pins that the key is there at all."""
    row = _mk(notes="two trucks", guys_auto=True, sort=3)
    assert set(row) == {"id", "name", "rate", "unit", "guys_auto", "sort", "notes",
                        "owner_email", "created_at", "updated_at", "default_work_types",
                        "favorite"}
    # EMPTY MEANS EVERY WORK TYPE, which is what keeps the column backwards compatible:
    # a row written before it existed still applies everywhere, exactly as it did when
    # `favorite` was the whole story.
    assert row["default_work_types"] == []
    assert isinstance(row["rate"], float)
    assert isinstance(row["sort"], int)
    assert row["guys_auto"] is True
    assert row["owner_email"] == "hanz@wetreadwell.com"


# ── favorite: is this labor type a default? ────────────────────────────
#
# The column the Labor tab exists to make meaningful. Before it, EVERY row in this table behaved
# as a default because there was no other tab a custom line could come from — the two-step ALTER
# in both schema files backfills every row that predates the column to `true` (preserving that
# old behaviour for what already exists) and then moves the column's own default to `false` (so a
# type created on the new Labor tab is NOT automatically a default). This block pins the half of
# that contract Python can see: what `validate_labor`/`create_labor`/`_shape_labor` do with the
# key on a fresh row. The backfill itself is SQL and is not exercised here — see
# test_creating_and_listing's sibling tests above for the same posture on `default_work_types`.
def test_creating_defaults_favorite_to_false():
    """A brand new labor type, created without naming `favorite` at all, is NOT a default. This is
    the Python-side half of "create it, then decide if it's a default" — the half that has to
    agree with the schema's own `alter column favorite set default false`, or a caller that goes
    around the ALTER (this function) and a caller that does not (a raw SQL insert) would disagree
    about what a blank row means.

    Mutation: change `bool(payload.get("favorite"))` to default `True` in validate_labor, and a
    line typed on the new Labor tab appears in every new bid the moment it is saved — the
    two-tabs-two-actions design this table exists for, undone in one line."""
    assert library.validate_labor({"name": "x"})["favorite"] is False
    assert library.validate_labor({"name": "x", "rate": 40})["favorite"] is False


def test_favorite_is_coerced_not_validated():
    """Same posture as guys_auto and an item's own favorite: any truthy/falsy value means exactly
    what it says, and there is no invalid value to reject."""
    assert library.validate_labor({"name": "x", "favorite": True})["favorite"] is True
    assert library.validate_labor({"name": "x", "favorite": "yes"})["favorite"] is True
    assert library.validate_labor({"name": "x", "favorite": 0})["favorite"] is False
    assert library.validate_labor({"name": "x"})["favorite"] is False


def test_favorite_round_trips_through_create_and_patch(store):
    """The whole mechanism the new Labor tab and the Defaults tab's browse-and-search share:
    a labor type can be created not-a-default and made one afterward, on a different screen, with
    a plain boolean PATCH — the same `{ favorite: true }` body setDefault already sends for an
    item or an assembly."""
    row = _mk()
    assert row["favorite"] is False, "a freshly created labor type opened as a default"
    made_default = library.update_labor(row["id"], {"favorite": True})
    assert made_default["favorite"] is True
    # AND BACK OFF, the same write Remove on the Defaults tab sends — this does not delete the
    # labor type, it only stops it seeding a new bid. It must still be listed afterward.
    taken_off = library.update_labor(row["id"], {"favorite": False})
    assert taken_off["favorite"] is False
    assert [r["id"] for r in library.list_labor()] == [row["id"]], (
        "un-favoriting a labor type took it off the catalog — it should only stop it being a "
        "default, the same as Remove already means for an item or an assembly")


def test_favorite_is_read_honestly_off_whatever_the_store_holds(store):
    """`_shape_labor` reports what is there — it does not invent a "yes" the way
    `_coerce_work_types([])` invents "applies everywhere" for an absent `default_work_types`.
    A row with no `favorite` key at all (every row before the migration's first ALTER backfills
    it) reads `False`; a row the migration or an admin has set to `true` reads `True`. The two
    columns disagree about what a missing value means for opposite, deliberate reasons, and this
    is the one this table would get wrong if it copied the other's shape instead of stating its
    own."""
    store["library_labor"].append({"id": "l1", "name": "No favorite key at all"})
    store["library_labor"].append({"id": "l2", "name": "Backfilled", "favorite": True})
    store["library_labor"].append({"id": "l3", "name": "Explicitly off", "favorite": False})
    got = {r["id"]: r["favorite"] for r in library.list_labor()}
    assert got == {"l1": False, "l2": True, "l3": False}


def test_a_partial_patch_leaves_favorite_alone_unless_named(store):
    """The same guarantee `test_a_partial_update_only_touches_what_it_names` pins for the module as
    a whole, asked specifically of the field a stray write would most visibly wreck: a rate edit
    on the new Labor tab must not silently un-default a line the Defaults tab already favorited."""
    row = _mk()
    library.update_labor(row["id"], {"favorite": True})
    edited = library.update_labor(row["id"], {"rate": 61})
    assert edited["rate"] == 61.0
    assert edited["favorite"] is True, "editing the rate turned favorite back off"


@pytest.mark.parametrize("rel", ["supabase_schema.sql", "staging/schema_pg.sql"])
def test_both_schemas_add_favorite_in_two_steps_so_existing_rows_stay_defaults(rel):
    """THE ORDER IS THE BACKFILL. `add column ... default true` fills every row that exists when
    it runs -- Travel, and every line already typed into the Defaults tab -- with true, so nothing
    Kyle bids with stops being a default. Only THEN does the column's default move to false, so a
    line created on the Labor tab afterwards is not one. Swap the two, or collapse them into one
    `default false` ADD, and every existing row is un-defaulted the moment the DDL runs.

    Both files, because staging runs its own Postgres and prod runs Supabase -- DDL twice, or one
    drifts. And both AFTER the Travel seed insert, so a fresh database gets Travel backfilled too.

    Mutation: swap the two ALTER lines in either file, or change the first to `default false`."""
    import pathlib
    import re
    sql = (pathlib.Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")
    add = ("alter table public.library_labor add column if not exists favorite boolean "
           "not null default true;")
    flip = "alter table public.library_labor alter column favorite set default false;"
    assert sql.count(add) == 1, "%s does not add favorite exactly once, defaulting true" % rel
    assert sql.count(flip) == 1, "%s never moves favorite's default to false" % rel
    created = sql.index("create table if not exists public.library_labor")
    seeded = sql.index("insert into public.library_labor")
    assert created < seeded < sql.index(add) < sql.index(flip), (
        "%s runs the favorite DDL out of order -- the backfill has to come first, after the "
        "Travel seed" % rel)
    assert not re.search(r"library_labor\s+add column[^;]*favorite[^;]*default\s+false", sql), (
        "%s adds favorite with default false in one step, un-defaulting every existing row" % rel)


class _Numeric102Client:
    """A store that rounds `rate` on the way in, the way numeric(10,2) actually does."""

    def __init__(self, inner):
        self.inner = inner
        self.store = inner.store
        self.captures = inner.captures

    def table(self, name):
        inner = self.inner.table(name)
        if name != library.LABOR:
            return inner
        real_insert = inner.insert

        def insert(row):
            row = dict(row)
            if row.get("rate") is not None:
                row["rate"] = round(float(row["rate"]) + 1e-9, 2)
            return real_insert(row)

        inner.insert = insert
        return inner


@pytest.fixture()
def rounding_store(fake_supabase, monkeypatch):
    st = {"library_labor": []}
    monkeypatch.setattr(library, "get_client",
                        lambda: _Numeric102Client(fake_supabase(st)))
    return st


def test_a_create_answers_with_what_the_store_holds_not_what_was_sent(rounding_store):
    """`rate` is numeric(10,2). A create that replies with the figure it SENT shows a rate
    that silently changes on the next reload — the artefact-versus-truth mistake this repo
    has already paid for elsewhere. update_labor reads back; so does this."""
    row = library.create_labor({"name": "Mobilization", "rate": "45.567"}, None)
    assert row["rate"] == 45.57
    assert library.list_labor()[0]["rate"] == 45.57, "the two must not disagree"


def test_postgrest_string_numerics_are_read_back_as_numbers(store):
    """numeric(10,2) comes back over the wire as "45.00". The estimate multiplies by it, so the
    coercion happens once here rather than in every caller."""
    store["library_labor"].append(
        {"id": "l1", "name": "Legacy", "rate": "45.00", "sort": "2", "unit": "days"})
    got = library.list_labor()[0]
    assert got["rate"] == 45.0 and isinstance(got["rate"], float)
    assert got["sort"] == 2 and isinstance(got["sort"], int)


def test_a_row_written_before_a_column_existed_still_reads(store):
    store["library_labor"].append({"id": "l1", "name": "Legacy"})
    got = library.list_labor()[0]
    assert got["rate"] == 0.0 and got["unit"] == "hours"
    assert got["guys_auto"] is False and got["sort"] == 0 and got["notes"] == ""


def test_the_list_is_sorted_by_position_then_name(store):
    _mk(name="Banana", sort=1)
    _mk(name="apple", sort=1)
    _mk(name="Aardvark", sort=2)
    # Position wins over name, and the name tie-break is case-insensitive: sorted raw, "Banana"
    # would come before "apple" purely because a capital B is a smaller byte than a lower-case a.
    assert [r["name"] for r in library.list_labor()] == ["apple", "Banana", "Aardvark"]


def test_updating_one_field_leaves_the_rest_alone(store):
    row = _mk(notes="two trucks", guys_auto=True)
    got = library.update_labor(row["id"], {"rate": 60})
    assert got["rate"] == 60.0
    assert got["name"] == "Mobilization" and got["notes"] == "two trucks"
    assert got["guys_auto"] is True


def test_updating_something_that_is_gone_returns_none(store):
    assert library.update_labor("nope", {"rate": 1}) is None
    assert library.delete_labor("nope") is False


def test_two_lines_may_share_a_name(store):
    """Unlike a vendor or a division. Those lists exist to stop one supplier having three
    spellings; this one is a list of things to do, and two crews both mobilizing at different
    rates is a real thing to want. The DDL's index on the live name is not unique."""
    a, b = _mk(rate=45), _mk(rate=60)
    assert a["id"] != b["id"]
    assert len(library.list_labor()) == 2


# ── soft delete ───────────────────────────────────────────────────────
def test_a_deleted_line_disappears_from_the_list_but_the_row_survives(store):
    row = _mk()
    assert library.delete_labor(row["id"]) is True
    assert library.list_labor() == []
    assert library.get_labor(row["id"]) is None
    # The row itself is still there, carrying a deleted_at — every destructive action in this
    # tool is recoverable, and a rate somebody typed by hand is reference data.
    stored = [r for r in store["library_labor"] if r["id"] == row["id"]]
    assert len(stored) == 1 and stored[0]["deleted_at"]


def test_deleting_twice_is_a_no_op_not_a_second_success(store):
    row = _mk()
    assert library.delete_labor(row["id"]) is True
    assert library.delete_labor(row["id"]) is False


# ── Travel: one reserved row, named by the schema and by nothing else ─────────
def test_nothing_in_python_seeds_travel_into_this_table(store):
    """`_list_refs` deliberately hands back DEFAULTS when its table is empty — that is how the
    Divisions and Units lists ship with something in them. Copying that shape here would put a
    SECOND statement of Travel's rate in Python, beside the one in `travelSeed()` — and the note
    above travelSeed records what two copies of that row did within a day of existing.

    THE ROW IS SEEDED BY THE SQL, once, in both schema files. An empty table is therefore the
    honest answer everywhere the DDL has not run, and the frontend falls back to travelSeed()'s
    own constant there rather than showing nothing."""
    assert library.list_labor() == []
    assert store["library_labor"] == []
    assert library._ref_defaults(library.LABOR) == (), \
        "library_labor must not be given seeded defaults the way the reference lists are"


def test_the_api_can_never_name_a_row_so_the_reserved_id_cannot_be_forged(store, as_admin):
    """THE DOUBLE-TRAVEL HAZARD, SHUT AT THE DOOR. `travel` is the id `migrateModel` finds the
    Travel row by on every draft ever saved, and `seedLibraryLabor` treats it as the one id that
    may overwrite a row already on the model. A second row holding it would be applied to bids
    depending on which the server listed first.

    So a caller does not get to choose. `LibraryLaborIn` has no `id` field and `create_labor`
    does `row["id"] = str(uuid.uuid4())` unconditionally — an id in the body is dropped like any
    other unknown key, exactly the way `validate_item` drops one.

    EXECUTED THROUGH THE ENDPOINT, not read off the source: "the field is not on the model" and
    "the field is ignored" are different claims and only the second one matters.

    Mutation: add `id` to LibraryLaborIn and let create_labor honour it. The POST below then
    stores a row whose id is `travel`, and the Defaults tab lists two Travels."""
    r = client.post("/api/library/labor",
                    json={"id": "travel", "name": "Drive time", "rate": 99, "unit": "days"})
    assert r.status_code == 200, r.text
    made = r.json()["row"]
    assert made["id"] != "travel", (
        "the API let a caller name a row `travel` — that row now competes with the seeded one "
        "for every bid")
    assert len(made["id"]) >= 32, "the id is not the uuid create_labor is supposed to mint"
    assert [x["id"] for x in store["library_labor"]] == [made["id"]]


def test_editing_travel_leaves_the_fields_the_form_does_not_write_alone(store, as_admin):
    """THE CONTRACT THE Reset BUTTON AND THE Edit FORM BOTH RELY ON. Both send `name`, `rate` and
    `unit` and nothing else; `guys_auto` is what keeps Travel's Guys column tracking the crew's
    man-days, and `sort` is what keeps it first in the list. A PATCH that blanked either would
    silently change how every new bid prices travel, or move the line.

    `validate_labor(partial=True)` is what guarantees it — it touches only the keys the caller
    actually named — and this is that guarantee run against the store rather than read.

    Mutation: drop the `partial=True` from update_labor's validate call. `guys_auto` then comes
    back False (the column default for a key nobody sent) and Travel stops following the crew."""
    store["library_labor"].append({
        "id": "travel", "name": "Travel", "rate": 33.0, "unit": "hours", "guys_auto": True,
        "sort": -1, "notes": "seeded by the schema", "owner_email": None,
        "created_at": "2026-09-19T00:00:00Z", "updated_at": "2026-09-19T00:00:00Z",
        "deleted_at": None})
    r = client.patch("/api/library/labor/travel",
                     json={"name": "Travel", "rate": 41.5, "unit": "hours"})
    assert r.status_code == 200, r.text
    row = r.json()["row"]
    assert row["rate"] == 41.5, "the edit did not land"
    assert row["guys_auto"] is True, (
        "a rate edit turned Travel's guys_auto off — its Guys column stops following the crew")
    assert row["sort"] == -1, "a rate edit moved Travel's position in the list"
    assert row["notes"] == "seeded by the schema", "a rate edit blanked the notes"
    # One row, still. An edit is not an insert.
    assert [x["id"] for x in store["library_labor"]] == ["travel"]


def test_deleting_travel_is_refused_not_silently_soft_deleted(store, as_admin):
    """WHY Reset IS A PATCH AND NOT A DELETE, said at the level where it is a fact about the API
    rather than about a button — and, since the Labor tab, no longer just an argument: the row is
    now genuinely reachable from a DELETE icon on a real table of real rows, not only from the one
    Reset button that always PATCHed. Something has to hold the door shut at the layer a UI icon
    cannot be trusted to.

    A soft delete would read fine on screen: list_labor() would stop answering with the row and
    the page would fall back to travelSeed()'s $33.00/hr, so Travel would neither disappear from
    the list nor from a bid already using it. What it would ALSO do is take the id with it —
    `update_labor` and `get_labor` both filter on `deleted_at is null`, so the row would become
    unaddressable, and the only way to make a row called `travel` again would be by hand in SQL
    (the test above pins that the API cannot mint one). The Edit control would go with it and
    Travel would be exactly as uneditable as it was before any of this shipped.

    Mutation: delete the `if labor_id == "travel"` guard from delete_labor. This test goes red
    with `ValidationError` never raised and the row's `deleted_at` no longer null."""
    store["library_labor"].append({
        "id": "travel", "name": "Travel", "rate": 41.5, "unit": "hours", "guys_auto": True,
        "sort": -1, "notes": None, "owner_email": None, "favorite": True,
        "created_at": "2026-09-19T00:00:00Z", "updated_at": "2026-09-19T00:00:00Z",
        "deleted_at": None})
    with pytest.raises(library.ValidationError) as exc:
        library.delete_labor("travel")
    assert "travel" in str(exc.value).lower() and "delete" in str(exc.value).lower()
    # FAIL-CLOSED BEFORE THE STORE IS EVEN ASKED. The row is untouched — still there, still live,
    # rate unchanged — because the id is refused before any query runs, not because a query
    # happened to fail. A guard that only checked AFTER reading the row would still refuse the
    # delete, but this pins the cheaper and safer shape.
    stored = [r for r in store["library_labor"] if r["id"] == "travel"][0]
    assert stored["deleted_at"] is None and stored["rate"] == 41.5

    # THE UI ICON IS A NICETY, NOT THE GUARD. A caller that goes around it — a stale tab, a script,
    # a future admin screen that forgets to hide the icon — meets the same refusal the endpoint
    # gives: 400, not 404, because `travel` is very much still on the list. A 404 here would read
    # as "already gone" to whatever called it, which is the wrong story to tell about a row that
    # is refusing to leave on purpose.
    r = client.delete("/api/library/labor/travel")
    assert r.status_code == 400, r.text
    assert "travel" in r.json()["detail"].lower()
    assert client.get("/api/library/labor").json()["labor"][0]["id"] == "travel", (
        "the refused delete still took Travel off the list")

    # AND IT IS STILL FULLY ITSELF AFTERWARDS — patchable, listed, on the rate it was on. A guard
    # that refused the delete but left the row half-broken would be a different bug wearing the
    # same status code.
    r2 = client.patch("/api/library/labor/travel", json={"rate": 33.0})
    assert r2.status_code == 200, r2.text
    assert r2.json()["row"]["rate"] == 33.0


def test_a_non_admin_cannot_reach_the_travel_guard_either(store, as_user):
    """The 403 for a regular user fires before the 400 for the reserved id would — admin-gating
    is checked first, the same order `test_the_gate_is_checked_before_the_write_not_after` pins
    for a create. Two separate refusals, and this is the one that proves they do not race."""
    store["library_labor"].append({
        "id": "travel", "name": "Travel", "rate": 33.0, "unit": "hours", "guys_auto": True,
        "sort": -1, "notes": None, "owner_email": None, "favorite": True,
        "created_at": "2026-09-19T00:00:00Z", "updated_at": "2026-09-19T00:00:00Z",
        "deleted_at": None})
    assert client.delete("/api/library/labor/travel").status_code == 403


# ── endpoints ─────────────────────────────────────────────────────────
def test_the_endpoints_round_trip(store, as_admin):
    r = client.post("/api/library/labor",
                    json={"name": "Mobilization", "rate": "$45.00", "unit": "Days"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    row = body["row"]
    assert row["rate"] == 45.0 and row["unit"] == "days"

    r = client.get("/api/library/labor")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert [x["id"] for x in r.json()["labor"]] == [row["id"]]

    r = client.patch("/api/library/labor/%s" % row["id"], json={"rate": 60, "notes": "2 trucks"})
    assert r.status_code == 200, r.text
    assert r.json()["row"]["rate"] == 60.0 and r.json()["row"]["notes"] == "2 trucks"

    r = client.delete("/api/library/labor/%s" % row["id"])
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get("/api/library/labor").json()["labor"] == []


def test_anybody_signed_in_can_read_the_list(store, as_user):
    """The estimate has to offer these lines mid-bid. A gate on the READ would stop a bid halfway
    through, silently — the same reasoning the empty `api` tuple for /library.html records."""
    _mk()
    r = client.get("/api/library/labor")
    assert r.status_code == 200
    assert [x["name"] for x in r.json()["labor"]] == ["Mobilization"]


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/library/labor", {"name": "Snuck In", "rate": 1}),
    ("patch", "/api/library/labor/l1", {"rate": 1}),
    ("delete", "/api/library/labor/l1", None),
])
def test_a_regular_user_cannot_change_the_list(store, as_user, method, path, body):
    """These rows carry a rate, and a rate is what a job sells for. Gated like Vendors."""
    kw = {"json": body} if body is not None else {}
    assert getattr(client, method)(path, **kw).status_code == 403


def test_the_gate_is_checked_before_the_write_not_after(store, as_user):
    """A 403 that still inserted the row would be worse than no gate at all — the list would grow
    while telling the person it hadn't."""
    client.post("/api/library/labor", json={"name": "Snuck In", "rate": 1})
    assert store["library_labor"] == []


@pytest.mark.parametrize("body,word", [
    ({"name": "", "rate": 1}, "name"),
    ({"name": "x", "rate": -5}, "negative"),
    ({"name": "x", "rate": "abc"}, "number"),
    ({"name": "x", "rate": 99999999}, "large"),
    ({"name": "x", "unit": "weeks"}, "hours"),
])
def test_a_bad_payload_is_a_400_with_a_message_not_a_500(store, as_admin, body, word):
    r = client.post("/api/library/labor", json=body)
    assert r.status_code == 400, r.text
    assert word in r.json()["detail"].lower()


def test_writing_to_something_that_is_gone_is_a_404(store, as_admin):
    assert client.patch("/api/library/labor/nope", json={"rate": 1}).status_code == 404
    assert client.delete("/api/library/labor/nope").status_code == 404


@pytest.mark.parametrize("payload", [
    {}, {"name": None}, {"name": "x", "rate": []}, {"name": "x", "sort": {}},
    {"name": "x", "unit": ["hours"]}, {"name": "x", "notes": 5},
])
def test_hostile_payloads_never_500(store, as_admin, payload):
    r = client.post("/api/library/labor", json=payload)
    assert r.status_code in (200, 400, 422), (payload, r.status_code, r.text)


# ── which work types a default belongs to ─────────────────────────
def test_the_work_types_come_from_markup_not_a_fourth_copy():
    """A hand-typed list is how a default ends up filed under a name nothing looks up -- which
    on screen is indistinguishable from a default that is simply switched off.

    And `combo` is NOT one: it is what detect_work_type() returns for which PROPOSAL to write,
    not a sheet tab. A combo job runs on epoxy AND polish, so it inherits both lists."""
    import markup
    assert library.WORK_TYPES is markup.TABS, (
        "the library keeps its own copy of the work types; it will drift from markup's")
    assert "combo" not in library.WORK_TYPES
    assert "global" not in library.WORK_TYPES, (
        "global is markup's word for every tab; a default says that by naming none")


def test_empty_means_every_work_type_so_nothing_already_set_stops_applying():
    """THE BACKWARDS-COMPATIBILITY GUARANTEE, and the reason no data migration was written.
    Every row that predates the column reads [] and still applies everywhere."""
    assert library._coerce_work_types(None) == []
    assert library._coerce_work_types([]) == []
    assert library._coerce_work_types("") == []


def test_an_off_list_work_type_is_refused_rather_than_dropped():
    """Dropped, it would save as "applies everywhere" -- the opposite of what was asked for,
    silently. markup.py refuses an off-list layout for exactly this reason."""
    for bad in ("combo", "Polish!", "sealer", "global", "epoxy2"):
        with pytest.raises(library.ValidationError) as exc:
            library._coerce_work_types([bad])
        assert "work type" in str(exc.value)


def test_work_types_are_a_set_in_the_sheets_own_order():
    """Duplicates collapse and order is the workbook's, not the order somebody clicked: this is
    a set of tabs, and two orderings of the same set must compare equal."""
    assert (library._coerce_work_types(["epoxy", "polish", "epoxy"])
            == library._coerce_work_types(["polish", "epoxy"]))
    assert library._coerce_work_types(["gyp", "polish"]) == ["polish", "gyp"]
    assert library._coerce_work_types(["EPOXY", " Polish "]) == ["polish", "epoxy"]


def test_a_labor_line_carries_its_work_types_through_a_write(store):
    """The column is useless if validate_labor drops it on the way to the store."""
    row = _mk(default_work_types=["epoxy", "polish"])
    assert row["default_work_types"] == ["polish", "epoxy"]
