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


# ── the admin gate on the vendor list ─────────────────────────────────
def test_anybody_signed_in_can_read_the_vendor_list(store, as_user):
    """The Items tab's dropdown needs it, and an estimator has to be able to record where a
    material came from. Gating the READ would break the page for everyone but two people."""
    library.create_vendor({"name": "Sika"}, None)
    r = client.get("/api/library/vendors")
    assert r.status_code == 200
    assert [v["name"] for v in r.json()["vendors"]] == ["Sika"]
    assert r.json()["usage"] == {}


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/library/vendors", {"name": "Sika"}),
    ("patch", "/api/library/vendors/v1", {"name": "Sika"}),
    ("delete", "/api/library/vendors/v1", None),
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


def test_the_duplicate_refusal_reaches_the_caller_as_a_readable_400(store, as_admin):
    client.post("/api/library/vendors", json={"name": "Sika"})
    r = client.post("/api/library/vendors", json={"name": "sika"})
    assert r.status_code == 400 and "already" in r.json()["detail"].lower()


def test_the_gate_is_checked_before_the_write_not_after(store, as_user):
    """A 403 that still inserted the row would be worse than no gate at all — the list would grow
    while telling the person it hadn't."""
    client.post("/api/library/vendors", json={"name": "Snuck In"})
    assert store["library_vendors"] == []
