"""The Items and Assemblies page, executed out of the real library.js.

Batch 6 rebuilt both tables from Hanz's screenshots. EXECUTED, NOT GREPPED — the interesting
failures here are all invisible to a source assertion:

  * `refreshNumbers()` writes the computed cells BY POSITION on a table `renderPanel()` built.
    The two functions never see each other, so a column inserted ahead of them writes the
    quantity into the waste box. Rendering a row and comparing where the cell landed with the
    index the updater uses is the only honest check.
  * A grep for "ADMIN" in the vendors render proves the variable is mentioned, not that a
    non-admin is denied an editable field.
  * "buy_qty is coerced to a number" would match its own declaration.

The numbers come from the REAL library-core.js, so nothing here can pass against a stub that
disagrees with the pricing engine.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "library-ui-harness.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the page says what it is ──────────────────────────────────────────
@needs_node
def test_the_page_is_called_items_and_assemblies(ran):
    assert ran["page"]["h1"] == "Items and Assemblies"
    assert ran["page"]["title"].startswith("Items and Assemblies")


@needs_node
def test_each_tab_says_what_belongs_in_it(ran):
    """Hanz asked for these two sentences by name. The tabs hold the same materials seen two ways,
    and which way is not self-evident from a table of numbers."""
    assert ran["page"]["itemsIntro"], "the Items tab doesn't say items are entered as we buy them"
    assert ran["page"]["assembliesIntro"]


@needs_node
def test_the_material_column_names_the_manufacturer(ran):
    """"Material (how the manufacturer names it)" — because the whole point of the column is that
    it matches the invoice, not what Treadwell calls the product in conversation."""
    assert ran["page"]["materialHeaderNamesTheManufacturer"]


@needs_node
def test_the_headers_hanz_asked_to_change_have_changed(ran):
    p = ran["page"]
    assert p["coveragePerUnitHeader"] and p["wasteHeader"] and p["roundupHeader"]
    assert p["vendorsTab"], "there is no Vendors tab"
    assert p["noCoverageSfHeader"], "Coverage (SF) is still on the Items tab"
    assert p["noRoleHeader"], "the Role column is still there"


# ── Items ─────────────────────────────────────────────────────────────
@needs_node
def test_division_is_a_dropdown_of_the_three_divisions(ran):
    assert ran["items"]["divisionOptions"] == [
        "—", "Polished Concrete", "Epoxy", "Gypsum Underlayment"]


@needs_node
def test_buy_by_became_a_quantity_and_a_unit(ran):
    """"5 Gal" is two facts, and pricing needs them apart: the pack size is what turns a needed
    16.8 gallons into four pails."""
    assert ran["items"]["hasBuyQty"] and ran["items"]["hasUnitDropdown"]
    assert ran["items"]["unitOptions"][-3:] == ["Gallon", "Kit", "Bag"]


@needs_node
def test_a_legacy_unit_is_offered_back_rather_than_silently_changed(ran):
    """"Gal" is not on the new list, and a select that quietly displayed "Gallon" instead would
    rewrite the row the next time anybody touched it."""
    assert ran["items"]["legacyUnitKept"]


@needs_node
def test_the_cost_wears_a_dollar_sign(ran):
    assert ran["items"]["costWearsADollarSign"]


@needs_node
def test_coverage_left_the_items_tab(ran):
    assert ran["items"]["hasCoverage"] is False


@needs_node
def test_the_vendor_is_a_dropdown_that_keeps_an_off_list_value(ran):
    """A vendor removed from the list must still show on the material bought from it — an item
    records where it actually came from — and must not appear twice when it is also on the list."""
    assert ran["items"]["hasVendorDropdown"]
    assert ran["items"]["offListVendorKept"]
    assert ran["items"]["offListVendorNotDuplicated"]


@needs_node
def test_a_vendor_can_still_be_recorded_before_an_admin_curates_the_list(ran):
    """Only an admin may add to the vendor list, so a dropdown fed ONLY by that list would leave an
    estimator on a fresh install unable to say where a material came from — a text box replaced by
    an empty menu. Suppliers already named on materials are offered too."""
    assert ran["vendorOptions"]["withNoCuratedList"] == [True, True]
    assert ran["vendorOptions"]["uncuratedStillOffered"]


@needs_node
def test_the_curated_spelling_wins_over_a_sloppier_one_on_an_item(ran):
    """Otherwise the union re-creates the duplication the list exists to end: "sika" typed last
    month reappearing beside "Sika"."""
    assert ran["vendorOptions"]["curatedSpellingWins"], ran["vendorOptions"]["messyOpts"]


@needs_node
def test_the_material_name_offers_the_existing_names(ran):
    assert ran["items"]["nameOffersAutosuggest"] and ran["items"]["datalistFilled"]


@needs_node
def test_a_similar_name_is_pointed_out_without_being_blocked(ran):
    """Hanz asked for "a hint … to avoid duplicates". A hint, because the same product legitimately
    appears twice at different coverages — a hard block would stop real work."""
    d = ran["dupes"]
    assert d["onSimilar"] == ["OPF Primer"]
    assert d["notItself"], "a row accused itself of being a duplicate"
    assert d["quietWhileTyping"] == [], "two characters is not yet a name"
    assert d["unrelated"] == []


@needs_node
def test_both_dates_are_shown_in_business_time(ran):
    d = ran["dates"]
    assert d["usesBusinessTime"], "the stamps aren't going through TW.fmtBizDateTime"
    assert d["saysAddedAndPrice"]


@needs_node
def test_a_material_whose_price_never_moved_does_not_look_freshly_priced(ran):
    """The stamp answers "how old is this number?". Showing the row's creation date there, or
    today's date, would answer it wrongly — which is the whole reason it is its own column."""
    assert ran["dates"]["neverPricedSaysSo"]
    assert ran["dates"]["neverPricedShowsNoDate"]


@needs_node
def test_the_pack_size_is_coerced_to_a_number_like_the_other_two(ran):
    """Executed: the list the handler actually consults. A string "5" in the model works by luck
    while dividing and concatenates the first time anything multiplies."""
    assert ran["numericFields"] == ["unit_cost", "coverage", "buy_qty"]


# ── Vendors ───────────────────────────────────────────────────────────
@needs_node
def test_a_regular_user_can_read_the_vendor_list_but_not_edit_it(ran):
    """Decided with Hanz: managing the LIST is admin-only, picking a vendor is not. So the read-only
    state is a real state — the names, no fields, and who to ask."""
    v = ran["vendors"]
    assert v["userStillSeesTheNames"]
    assert v["userGetsNoInputs"], "a non-admin was given an editable vendor field"
    assert v["userGetsNoDeleteButton"]
    assert v["userToldWhoToAsk"], "the read-only note is hidden, so the tab looks broken"
    assert v["userNotOfferedAddButtons"], "an Add button that 403s on click"


@needs_node
def test_an_admin_gets_the_editable_list(ran):
    v = ran["vendors"]
    assert v["adminGetsInputs"] and v["adminGetsDelete"] and v["adminOfferedAdd"]
    assert v["adminNotShownTheReadOnlyNote"]


@needs_node
def test_the_list_says_how_many_materials_name_each_vendor(ran):
    """So a delete can say what it affects before it happens, the way removing a material already
    says how many assemblies use it."""
    assert ran["vendors"]["usageShown"]


# ── the assembly line ─────────────────────────────────────────────────
@needs_node
def test_the_role_column_is_gone_from_the_rendered_row(ran):
    assert ran["lines"]["roleColumnGone"]


@needs_node
def test_waste_and_roundup_are_on_every_line(ran):
    lines = ran["lines"]
    assert lines["hasWaste"] and lines["hasRoundupCheckbox"]
    assert lines["roundupTicksFromTheData"], \
        "the checkbox ignores the line's own flag — every row would read as rounded up"


@needs_node
def test_the_material_picker_is_a_search_box(ran):
    """"can we have a search bar and auto fill" — a <select> can only be searched by typing its
    first letters, which is no use to somebody who remembers "glaze"."""
    lines = ran["lines"]
    assert lines["pickerIsSearchable"] and lines["pickerShowsTheCurrentMaterial"]
    assert lines["pickerIsNotASelect"]


@needs_node
def test_the_two_rounding_modes_render_differently(ran):
    """A rounded line names the packs it buys; an unrounded one names the fraction it uses. If both
    read the same, the checkbox looks decorative."""
    assert ran["lines"]["firstQtyLabel"] == "11 Gal"
    assert ran["lines"]["secondQtyLabel"] == "10.45 Gallon"


@needs_node
def test_the_live_updater_writes_into_the_cells_the_row_actually_has(ran):
    """THE POSITIONAL CONTRACT, and the reason this file exists. `refreshNumbers` avoids rebuilding
    the row — that is what keeps the caret in the coverage field somebody is typing in — so it
    writes tds[4] and tds[5] on a table built by a different function. Adding a column ahead of
    them would put the quantity in the waste box, with no error anywhere."""
    lines = ran["lines"]
    assert lines["qtyIdx"] == 4 and lines["costIdx"] == 5, \
        "the rendered row moved its computed cells: %s" % lines
    assert lines["indexesAgree"], (
        "refreshNumbers writes %s but the row's qty/cost cells are at %s"
        % (lines["updaterIndexes"], [lines["qtyIdx"], lines["costIdx"]]))


@needs_node
def test_the_empty_state_spans_the_columns_that_now_exist(ran):
    assert ran["lines"]["placeholderColspan"] == ran["lines"]["tdCount"] == 7


@needs_node
def test_typed_text_resolves_to_a_material_or_to_nothing(ran):
    """Never a "closest" guess: silently picking the wrong primer is worse than saying no, because
    a wrong material still produces a plausible price."""
    p = ran["picker"]
    assert p["exact"] == "i2" and p["caseInsensitive"] == "i2" and p["trimmed"] == "i1"
    assert p["partialRefused"] is None, "a half-typed name was resolved to a material"
    assert p["unknownRefused"] is None and p["blank"] is None
