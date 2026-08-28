"""Items and Assemblies — the 2026-08-15 revision of the library (Hanz's screenshots).

The BETA library became a page about how Treadwell actually buys: an item is one line on an
invoice (a five-gallon pail, priced as the pail), an assembly says how much of it a system needs,
and the vendors are a list rather than a free-text box. Three of those changes move money.

WHAT THIS FILE IS DEFENDING. Every one of these can be wrong in a way that still looks like a
price, which is why each is pinned from BOTH directions — what a caller may write, and what a row
written before the column existed reads back as:

  * **`buy_qty` and the pack price.** `unit_cost` now means what the PACK costs. Read it as a
    per-unit price and a five-gallon pail prices the job at five times the bid; read a missing
    pack size as 0 and the arithmetic divides by zero.
  * **Waste on every line.** 5% when absent — and it must be the same 5% on both sides, because a
    row displaying 5% that was priced at 0% is a row lying about its own working.
  * **Roundup absent means yes.** The page has promised "you cannot buy 3.7 kits" since it
    shipped. Reading absent as false reprices every assembly built during the beta, downwards.
  * **The price date.** Hanz asked for a stamp that marks a PRICE REVISION, so correcting a
    spelling must not make a stale number look fresh. That is why it is a separate column from
    `updated_at`, which moves on every patch and is the assemblies' concurrency token.
  * **Who may change the vendor LIST.** Admin-only, decided with Hanz. Reading it is not: the
    Items dropdown needs it, and an estimator has to be able to say where a material came from.

Nothing here is migrated. Legacy rows are shaped ON READ, so an old row prices correctly whether
or not anybody has re-saved it, and no UPDATE ever touches somebody's hand-typed data.
"""
import pytest
from fastapi.testclient import TestClient

import library
import main
import profiles

client = TestClient(main.app)


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    st = {"library_items": [], "library_assemblies": [], "library_vendors": []}
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


def _mk_item(**kw):
    body = {"name": "OPF", "unit": "Gallon", "unit_cost": 85.3827, "coverage": 275}
    body.update(kw)
    return library.create_item(body, "hanz@wetreadwell.com")


# ── the pack: Qty + Unit, and a Cost that means the pail ──────────────
def test_a_pack_size_is_stored_so_a_cost_can_mean_the_pail():
    """`buy_qty` is the "5" of "5 Gal" and `unit_cost` is what that pail costs. Keeping them apart
    is what turns a needed 16.8 gallons into four pails instead of 16.8 mystery units."""
    assert library.validate_item({"name": "OPF", "buy_qty": "5"})["buy_qty"] == 5.0
    assert library.validate_item({"name": "OPF", "buy_qty": 2.5})["buy_qty"] == 2.5


@pytest.mark.parametrize("raw", [0, "0", "", None])
def test_a_pack_of_nothing_is_a_pack_of_one(raw):
    """Zero would divide the cost by zero and price the job at Infinity. Blank means nobody has
    said yet, and a purchase of one is the honest reading — it is also what every row written
    before this column existed genuinely is."""
    assert library.validate_item({"name": "x", "buy_qty": raw})["buy_qty"] == 1.0


def test_a_negative_or_nonsense_pack_size_is_refused_with_a_readable_message():
    for bad in (-3, "abc", True):
        with pytest.raises(library.ValidationError):
            library.validate_item({"name": "x", "buy_qty": bad})


def test_a_legacy_row_reads_as_a_pack_of_one_without_being_rewritten(store):
    """Read-shaped, not migrated. A row typed during the beta has no value in this column at all,
    and it must price exactly as it did — without an UPDATE touching hand-typed data."""
    it = _mk_item()
    store["library_items"][0].pop("buy_qty", None)
    assert library.get_item(it["id"])["buy_qty"] == 1.0
    assert store["library_items"][0].get("buy_qty") is None, "the stored row was rewritten"


def test_a_pasted_pack_size_survives_the_paste(store):
    r = client.patch("/api/library/items/%s" % _mk_item()["id"], json={"buy_qty": " 5 "})
    assert r.status_code == 200 and r.json()["item"]["buy_qty"] == 5.0


def test_a_division_or_unit_typed_in_the_wrong_case_becomes_the_offered_spelling():
    """So a pasted "epoxy" reads as the Division the dropdown offers rather than as an off-list
    value sitting beside the identical real one. Case only — this column was free text until today
    and old rows hold anything, so an unrecognised division is left exactly as typed."""
    assert library.validate_item({"name": "x", "category": "epoxy"})["category"] == "Epoxy"
    assert library.validate_item(
        {"name": "x", "category": "  gypsum   UNDERLAYMENT "})["category"] == "Gypsum Underlayment"
    assert library.validate_item({"name": "x", "unit": "gallon"})["unit"] == "Gallon"
    # Untouched: not one of the three, and not one of the three units.
    assert library.validate_item({"name": "x", "category": "Sealer"})["category"] == "Sealer"
    assert library.validate_item({"name": "x", "unit": "Gal"})["unit"] == "Gal"


def test_an_assembly_is_measured_in_SF_or_LF_and_says_which():
    """Hanz, 2026-08-28: "Coverage per Unit - is there a way we can change it from SF and LF?"

    Treadwell measures floor area in square feet and cove base in linear feet, and until today
    every assembly said SF because the create call hardcoded it - the column has always been
    persisted and has always been free text.

    CANONICALISED, because the Polish beta compares this value against the literal "LF" after
    upper-casing (polish-estimate.js stamps a takeoff row's unit from it). A row holding "lf" would
    load fine here and then silently fail to stamp anything over there."""
    assert library.validate_assembly({"name": "x", "unit": "LF"})["unit"] == "LF"
    assert library.validate_assembly({"name": "x", "unit": "lf"})["unit"] == "LF"
    assert library.validate_assembly({"name": "x", "unit": "  Lf "})["unit"] == "LF"
    assert library.validate_assembly({"name": "x", "unit": "sf"})["unit"] == "SF"
    # Absent means SF: what every existing row holds, and what a floor system is.
    assert library.validate_assembly({"name": "x"})["unit"] == "SF"
    assert library.validate_assembly({"name": "x", "unit": ""})["unit"] == "SF"


def test_an_off_list_assembly_unit_is_kept_rather_than_refused():
    """Same posture as DIVISIONS and ITEM_UNITS: offered, not enforced. This column was free text to
    24 characters before it had a vocabulary, so a legacy row may hold "sqft" or "Each" - and
    refusing it would make that assembly uneditable, which is worse than an odd label. The frontend
    reads anything unrecognised as SF so the label still matches the arithmetic that ran."""
    assert library.validate_assembly({"name": "x", "unit": "sqft"})["unit"] == "sqft"
    assert library.validate_assembly({"name": "x", "unit": "Each"})["unit"] == "Each"


def test_the_assembly_unit_round_trips_through_the_endpoint(store):
    """The whole point of the feature is that the choice STICKS - a relabel that is not persisted
    would read as a bug the next time somebody opened the assembly.

    And a PATCH carrying ONLY the unit is exactly what the select sends, so it must not disturb the
    name or the lines: `validate_assembly` is partial for a PATCH, and a unit-only body that reset
    the other columns would lose a takeoff to a relabel."""
    asm = library.create_assembly({"name": "Cove Base", "unit": "lf"}, "hanz@wetreadwell.com")
    assert asm["unit"] == "LF"

    r = client.patch("/api/library/assemblies/%s" % asm["id"], json={"lines": [
        {"item_id": "a", "coverage": 40}]})
    assert r.status_code == 200, r.text
    assert r.json()["assembly"]["unit"] == "LF", "a lines PATCH dropped the unit"

    back = client.patch("/api/library/assemblies/%s" % asm["id"], json={"unit": "SF"})
    assert back.status_code == 200, back.text
    assert back.json()["assembly"]["unit"] == "SF"
    assert back.json()["assembly"]["name"] == "Cove Base"
    assert len(back.json()["assembly"]["lines"]) == 1, "a unit PATCH dropped the lines"


def test_an_item_can_belong_to_multiple_divisions_without_losing_legacy_category(store):
    it = _mk_item(divisions=["epoxy", "Polished Concrete", "EPOXY"])
    got = library.get_item(it["id"])
    assert got["divisions"] == ["Epoxy", "Polished Concrete"]
    assert got["category"] == "Epoxy"
    stored = store["library_items"][0]
    assert stored["divisions"] == ["Epoxy", "Polished Concrete"]
    assert stored["category"] == "Epoxy"


def test_a_legacy_category_reads_as_one_division_without_being_rewritten(store):
    it = _mk_item(category="Gypsum Underlayment")
    store["library_items"][0].pop("divisions", None)
    got = library.get_item(it["id"])
    assert got["divisions"] == ["Gypsum Underlayment"]
    assert "divisions" not in store["library_items"][0]


def test_the_item_endpoint_round_trips_multiple_divisions(store):
    it = _mk_item()
    r = client.patch("/api/library/items/%s" % it["id"],
                     json={"divisions": ["Epoxy", "Polished Concrete"]})
    assert r.status_code == 200
    body = r.json()["item"]
    assert body["divisions"] == ["Epoxy", "Polished Concrete"]
    assert body["category"] == "Epoxy"


# ── the price date: a revision, not an edit ───────────────────────────
def test_a_brand_new_material_has_no_price_history(store):
    assert _mk_item()["cost_updated_at"] is None


def test_the_price_date_moves_when_the_cost_changes(store):
    it = _mk_item(unit_cost=85.3827)
    assert library.update_item(it["id"], {"unit_cost": 91.5})["cost_updated_at"], \
        "a price revision left no stamp"


def test_the_price_date_ignores_everything_that_is_not_the_cost(store):
    """Hanz: "Date modified update should only trigger when cost is modified which indicates a
    price revision." Correcting a spelling must not make a stale number look fresh."""
    it = _mk_item(unit_cost=85.3827)
    library.update_item(it["id"], {"unit_cost": 91.5})
    stamped = library.get_item(it["id"])["cost_updated_at"]
    for patch in ({"name": "OPF Primer"}, {"vendor": "Sherwin-Williams"}, {"buy_qty": 5},
                  {"unit": "Gallon"}, {"notes": "was mispriced"}, {"coverage": 300}):
        library.update_item(it["id"], patch)
        assert library.get_item(it["id"])["cost_updated_at"] == stamped, \
            "editing %s moved the price date" % list(patch)[0]
    # And `updated_at` DID move on those, or the row would look untouched to the concurrency check.
    assert library.get_item(it["id"])["updated_at"] > stamped


def test_saving_the_same_cost_again_is_not_a_price_revision(store):
    """The debounced PATCH re-sends the field as somebody tabs out of it, so the same number
    arrives routinely. Stamping that would date every price to the last time anybody looked."""
    it = _mk_item(unit_cost=85.3827)
    library.update_item(it["id"], {"unit_cost": 91.5})
    stamped = library.get_item(it["id"])["cost_updated_at"]
    library.update_item(it["id"], {"unit_cost": "91.50"})      # same number, pasted differently
    assert library.get_item(it["id"])["cost_updated_at"] == stamped


def test_clearing_a_cost_counts_as_a_revision(store):
    """"We no longer have a price for this" is a change an estimator needs to see the date of."""
    it = _mk_item(unit_cost=85.3827)
    assert library.update_item(it["id"], {"unit_cost": ""})["cost_updated_at"]


# ── waste factor and Roundup? on every line ───────────────────────────
def test_a_line_carries_its_waste_factor_and_roundup_flag(store):
    got = library.validate_assembly({"name": "x", "lines": [
        {"item_id": "a", "coverage": 275, "waste_pct": "7.5", "roundup": False}]})
    assert got["lines"][0]["waste_pct"] == 7.5
    assert got["lines"][0]["roundup"] is False


def test_a_line_without_a_waste_factor_defaults_to_five_percent_on_both_sides(store):
    """The two halves must agree. A row displaying 5% that was priced at 0% is a row lying about
    its own arithmetic, and this is the assertion that catches them drifting apart."""
    written = library.validate_assembly({"name": "x", "lines": [{"item_id": "a"}]})
    assert written["lines"][0]["waste_pct"] == 5.0
    asm = library.create_assembly({"name": "x", "lines": [{"item_id": "a", "coverage": 100}]},
                                  "hanz@wetreadwell.com")
    del store["library_assemblies"][0]["lines"][0]["waste_pct"]
    assert library.get_assembly(asm["id"])["lines"][0]["waste_pct"] == 5.0


def test_zero_waste_is_a_real_answer_and_stays_zero(store):
    """Kyle's own sheet has no waste factor, so his reproduced numbers depend on 0 surviving as 0
    rather than being treated as "unset" and defaulted back to 5."""
    got = library.validate_assembly({"name": "x", "lines": [
        {"item_id": "a", "waste_pct": 0}]})
    assert got["lines"][0]["waste_pct"] == 0.0
    asm = library.create_assembly({"name": "x", "lines": [{"item_id": "a", "waste_pct": 0}]},
                                  None)
    assert library.get_assembly(asm["id"])["lines"][0]["waste_pct"] == 0.0


def test_a_legacy_line_still_rounds_up(store):
    """The page has promised "you cannot buy 3.7 kits" since it shipped. Absent must read as true,
    or every assembly built during the beta silently reprices downwards."""
    asm = library.create_assembly({"name": "x", "lines": [{"item_id": "a", "coverage": 100}]},
                                  "hanz@wetreadwell.com")
    del store["library_assemblies"][0]["lines"][0]["roundup"]
    assert library.get_assembly(asm["id"])["lines"][0]["roundup"] is True


@pytest.mark.parametrize("bad,word", [(5000, "large"), (-5, "negative"), ("abc", "number")])
def test_an_impossible_waste_factor_is_refused_with_a_readable_message(store, bad, word):
    """Refused, not guessed at, matching how a bad COST behaves — 5000% and -5% are different
    mistakes and neither has an obvious intended value. The page keeps the typed number on screen
    with the message beside it, so nothing is lost; silently saving 100% instead would hide a
    fat finger inside a plausible-looking total."""
    with pytest.raises(library.ValidationError) as e:
        library.validate_assembly({"name": "x", "lines": [{"item_id": "a", "waste_pct": bad}]})
    assert word in str(e.value).lower()


def test_an_impossible_waste_factor_ALREADY_STORED_reads_clamped(store):
    """Defensive on the way out only. Nothing we write can produce this, but a hand-edited row or
    an import could, and 5000% would quietly multiply a bid by fifty."""
    asm = library.create_assembly({"name": "x", "lines": [{"item_id": "a", "coverage": 100}]}, None)
    store["library_assemblies"][0]["lines"][0]["waste_pct"] = 5000
    assert library.get_assembly(asm["id"])["lines"][0]["waste_pct"] == 100.0


def test_the_roundup_flag_round_trips_through_the_endpoint(store):
    asm = library.create_assembly({"name": "MACRO Flake"}, "hanz@wetreadwell.com")
    r = client.patch("/api/library/assemblies/%s" % asm["id"], json={"lines": [
        {"item_id": "a", "coverage": 275, "waste_pct": 10, "roundup": False}]})
    assert r.status_code == 200
    line = r.json()["assembly"]["lines"][0]
    assert line["roundup"] is False and line["waste_pct"] == 10.0


# ── vendors: a list, so one supplier keeps one spelling ───────────────
def test_a_vendor_needs_a_name(store):
    with pytest.raises(library.ValidationError):
        library.validate_vendor({"notes": "the paint people"})


def test_the_same_vendor_cannot_be_added_twice_under_two_spellings(store):
    """THE REASON THIS TABLE EXISTS. A free-text box grows "Sherwin", "Sherwin Williams" and "SW"
    as three suppliers, and then nobody can total what Treadwell spends with them."""
    library.create_vendor({"name": "Sherwin-Williams"}, "hanz@wetreadwell.com")
    for dupe in ("Sherwin-Williams", "sherwin-williams", "  SHERWIN-WILLIAMS  "):
        with pytest.raises(library.ValidationError) as e:
            library.create_vendor({"name": dupe}, "hanz@wetreadwell.com")
        assert "already" in str(e.value).lower()
    assert len(library.list_vendors()) == 1


def test_a_name_with_punctuation_is_matched_not_used_as_a_filter(store):
    """Compared in Python on purpose: commas and parentheses are PostgREST filter syntax, so
    "Sherwin-Williams, Inc." through an `ilike` filter would error or match the wrong rows."""
    library.create_vendor({"name": "Sherwin-Williams, Inc. (KC)"}, None)
    with pytest.raises(library.ValidationError):
        library.create_vendor({"name": "sherwin-williams, inc. (kc)"}, None)
    assert len(library.list_vendors()) == 1


def test_a_rename_onto_an_existing_vendor_is_refused_but_onto_itself_is_fine(store):
    a = library.create_vendor({"name": "Sherwin-Williams"}, None)
    b = library.create_vendor({"name": "Sika"}, None)
    with pytest.raises(library.ValidationError):
        library.update_vendor(b["id"], {"name": "sherwin-williams"})
    # Re-saving its own name — which the debounced PATCH does constantly — must not trip the check.
    got = library.update_vendor(a["id"], {"name": "Sherwin-Williams"})
    assert got["name"] == "Sherwin-Williams"


def test_a_deleted_vendor_leaves_the_materials_that_name_it_alone(store):
    """Items store the vendor NAME, deliberately. A delete here must not rewrite what a past
    purchase recorded — it only stops the name being offered on new ones."""
    v = library.create_vendor({"name": "Sika"}, None)
    it = _mk_item(vendor="Sika")
    assert library.delete_vendor(v["id"]) is True
    assert library.list_vendors() == []
    assert library.get_item(it["id"])["vendor"] == "Sika"


def test_a_second_delete_of_the_same_vendor_reports_gone(store):
    v = library.create_vendor({"name": "Sika"}, None)
    assert library.delete_vendor(v["id"]) is True
    assert library.delete_vendor(v["id"]) is False


def test_vendor_usage_counts_the_materials_naming_each_one(store):
    """So the tab can say what a delete affects before it happens, the way removing a material
    already says how many assemblies use it."""
    _mk_item(name="OPF", vendor="Sika")
    _mk_item(name="Glaze", vendor="sika")           # same supplier, sloppier typing
    _mk_item(name="Top", vendor="Sherwin-Williams")
    _mk_item(name="Unsourced", vendor="")
    assert library.vendor_usage() == {"sika": 2, "sherwin-williams": 1}


# ── divisions and units: admin lists too ─────────────────────────────────────
def test_division_and_unit_usage_count_live_items(store):
    _mk_item(name="Primer", divisions=["Epoxy", "Polished Concrete"], unit="Gallon")
    _mk_item(name="Top", category="epoxy", unit="gallon")
    _mk_item(name="Bag", divisions=["Gypsum Underlayment"], unit="Bag")
    assert library.division_usage() == {
        "epoxy": 2, "polished concrete": 1, "gypsum underlayment": 1}
    assert library.unit_usage() == {"gallon": 2, "bag": 1}


def test_a_deleted_division_or_unit_leaves_items_alone(store):
    d = library.create_ref(library.DIVISION_REFS, {"name": "Sealer"}, None, label="division")
    u = library.create_ref(library.UNIT_REFS, {"name": "Pail"}, None, label="unit")
    it = _mk_item(divisions=["Sealer"], unit="Pail")
    assert library.delete_ref(library.DIVISION_REFS, d["id"]) is True
    assert library.delete_ref(library.UNIT_REFS, u["id"]) is True
    got = library.get_item(it["id"])
    assert got["divisions"] == ["Sealer"]
    assert got["unit"] == "Pail"


@pytest.mark.parametrize("table,label", [
    (library.DIVISION_REFS, "division"),
    (library.UNIT_REFS, "unit"),
])
def test_reference_lists_refuse_case_insensitive_duplicates(store, table, label):
    library.create_ref(table, {"name": "Sika"}, None, label=label)
    with pytest.raises(library.ValidationError):
        library.create_ref(table, {"name": " sika "}, None, label=label)


# ── the admin gate on the vendor list ─────────────────────────────────
def test_anybody_signed_in_can_read_the_vendor_list(store, as_user):
    """The Items tab's dropdown needs it, and an estimator has to be able to record where a
    material came from. Gating the READ would break the page for everyone but two people."""
    library.create_vendor({"name": "Sika"}, None)
    r = client.get("/api/library/vendors")
    assert r.status_code == 200
    assert [v["name"] for v in r.json()["vendors"]] == ["Sika"]
    assert r.json()["usage"] == {}


@pytest.mark.parametrize("path,key,table,label", [
    ("/api/library/divisions", "divisions", library.DIVISION_REFS, "division"),
    ("/api/library/units", "units", library.UNIT_REFS, "unit"),
])
def test_anybody_signed_in_can_read_admin_reference_lists(store, as_user, path, key, table, label):
    library.create_ref(table, {"name": "Sika"}, None, label=label)
    r = client.get(path)
    assert r.status_code == 200
    assert [v["name"] for v in r.json()[key]] == ["Sika"]
    assert r.json()["usage"] == {}


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/library/vendors", {"name": "Sika"}),
    ("patch", "/api/library/vendors/v1", {"name": "Sika"}),
    ("delete", "/api/library/vendors/v1", None),
    ("post", "/api/library/divisions", {"name": "Sealer"}),
    ("patch", "/api/library/divisions/d1", {"name": "Sealer"}),
    ("delete", "/api/library/divisions/d1", None),
    ("post", "/api/library/units", {"name": "Pail"}),
    ("patch", "/api/library/units/u1", {"name": "Pail"}),
    ("delete", "/api/library/units/u1", None),
])
def test_a_regular_user_cannot_change_the_list(store, as_user, method, path, body):
    kw = {"json": body} if body is not None else {}
    r = getattr(client, method)(path, **kw)
    assert r.status_code == 403


def test_an_admin_can_add_rename_and_remove(store, as_admin):
    r = client.post("/api/library/vendors", json={"name": "Sika"})
    assert r.status_code == 200
    vid = r.json()["vendor"]["id"]
    assert client.patch("/api/library/vendors/%s" % vid,
                        json={"name": "Sika USA"}).json()["vendor"]["name"] == "Sika USA"
    assert client.delete("/api/library/vendors/%s" % vid).status_code == 200
    assert client.delete("/api/library/vendors/%s" % vid).status_code == 404


@pytest.mark.parametrize("path,key,new_name,renamed", [
    ("/api/library/divisions", "division", "Sealer", "Sealer Systems"),
    ("/api/library/units", "unit", "Pail", "Pail 5"),
])
def test_an_admin_can_add_rename_and_remove_reference_values(store, as_admin, path, key,
                                                            new_name, renamed):
    r = client.post(path, json={"name": new_name})
    assert r.status_code == 200
    rid = r.json()[key]["id"]
    assert client.patch("%s/%s" % (path, rid), json={"name": renamed}).json()[key]["name"] == renamed
    assert client.delete("%s/%s" % (path, rid)).status_code == 200
    assert client.delete("%s/%s" % (path, rid)).status_code == 404


def test_the_duplicate_refusal_reaches_the_caller_as_a_readable_400(store, as_admin):
    client.post("/api/library/vendors", json={"name": "Sika"})
    r = client.post("/api/library/vendors", json={"name": "sika"})
    assert r.status_code == 400 and "already" in r.json()["detail"].lower()


def test_the_gate_is_checked_before_the_write_not_after(store, as_user):
    """A 403 that still inserted the row would be worse than no gate at all — the list would grow
    while telling the person it hadn't."""
    client.post("/api/library/vendors", json={"name": "Snuck In"})
    assert store["library_vendors"] == []

# ══ one material, one name ═══════════════════════════════════════════════════
# Hanz, 2026-08-25, on two items with the same name: "dont allow". That reverses a deliberate
# earlier decision, and the reversal is sound because its premise expired — see _clashing_item.


def test_the_same_name_cannot_be_entered_twice(store):
    """The plain case, and the one the old on-screen hint already caught — but only as a hint."""
    _mk_item(name="Densifier")
    with pytest.raises(library.ValidationError) as e:
        _mk_item(name="Densifier")
    assert "already in the library" in str(e.value)
    assert "Densifier" in str(e.value), "the message does not say which material it clashes with"


def test_the_same_name_typed_differently_is_still_the_same_name(store):
    """THE CASE THAT MADE HANZ ASK. similarNames is a bidirectional SUBSTRING match, so
    "Concretebar" against "Concrete bar" was silent: neither string contains the other. Spacing,
    case and punctuation are all dropped before comparing, which is what makes those one name.

    Each spelling is asserted separately rather than in a loop, because a loop that stopped at the
    first failure would hide which of them the matcher actually misses."""
    _mk_item(name="Concrete bar")
    for retyped in ("Concretebar", "concretebar", "CONCRETE BAR", "Concrete-Bar",
                    "  Concrete   bar  "):
        with pytest.raises(library.ValidationError):
            _mk_item(name=retyped)


def test_a_plural_is_left_alone_on_purpose(store):
    """The explicit non-decision, written down so nobody "fixes" it later without reading why.

    Folding a trailing "s" would catch "Densifiers" against "Densifier" — and would also refuse
    genuinely different product names. This check BLOCKS, so a false positive costs more than a
    miss: the estimator is left unable to enter what is in front of them, while a real
    near-duplicate still gets the on-screen hint from similarNames."""
    _mk_item(name="Densifier")
    assert _mk_item(name="Densifiers")["name"] == "Densifiers"


def test_a_rename_cannot_collide_either(store):
    """create_item was the obvious half. Renaming an existing material onto another one reaches
    exactly the same end state and had no check at all — and the table has no unique constraint
    behind it, so nothing else would have stopped it."""
    _mk_item(name="Densifier")
    other = _mk_item(name="Sealer")
    with pytest.raises(library.ValidationError):
        library.update_item(other["id"], {"name": "densifier"})
    assert library.get_item(other["id"])["name"] == "Sealer", "the failed rename was saved anyway"


def test_a_material_can_still_be_saved_under_its_own_name(store):
    """The off-by-one that would make the library read-only: comparing a rename against every row
    INCLUDING itself refuses every save of an unchanged name — and the debounced PATCH sends the
    name on any edit to that row, so it would fire constantly and look like the server was down."""
    it = _mk_item(name="Densifier")
    assert library.update_item(it["id"], {"name": "Densifier"})["name"] == "Densifier"
    assert library.update_item(it["id"], {"unit_cost": 99})["unit_cost"] == 99
    assert library.update_item(it["id"], {"name": "Densifier XL"})["name"] == "Densifier XL"


def test_a_deleted_material_does_not_block_its_own_name(store):
    """_clashing_item reads list_items(), which is live rows only. A soft-deleted material holding
    its name hostage would be a name nobody can use and nobody can see to free up."""
    it = _mk_item(name="Densifier")
    library.delete_item(it["id"])
    assert _mk_item(name="Densifier")["name"] == "Densifier"
