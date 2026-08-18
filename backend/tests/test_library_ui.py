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
def test_division_is_a_checkbox_group_of_the_three_divisions(ran):
    assert ran["items"]["hasDivisionCheckboxes"]
    assert ran["items"]["divisionOptions"] == [
        "Polished Concrete", "Epoxy", "Gypsum Underlayment"]


@needs_node
def test_buy_by_became_a_quantity_and_a_unit(ran):
    """"5 Gal" is two facts, and pricing needs them apart: the pack size is what turns a needed
    16.8 gallons into four pails."""
    assert ran["items"]["hasBuyQty"] and ran["items"]["hasUnitDropdown"]
    assert all(u in ran["items"]["unitOptions"] for u in ["Gallon", "Kit", "Bag"])


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
def test_the_price_date_appears_without_a_reload(ran):
    """FOUND ON STAGING IN THE BROWSER, not by these tests. The server stamped the price revision
    correctly and the page went on saying "not since we started tracking" until F5, because the save
    handler adopted only `updated_at` — the stamp Hanz asked for, looking broken.

    Only the server can decide this date: it moves when the cost actually changed, not when a PATCH
    was sent. So the page has to take it from the reply."""
    p = ran["priceDate"]
    assert p["modelAdopted"] == "2026-08-15T00:00:01Z", "the reply's price date was thrown away"
    assert p["repainted"], "nothing was repainted, so the cell still shows the old date"
    assert p["repaintedSelector"] == '[data-item="i1"] .datescell'
    assert p["repaintShowsTheNewDate"] and p["repaintDroppedTheNeverLine"]


@needs_node
def test_a_patch_that_did_not_touch_the_cost_repaints_nothing(ran):
    """Repainting on every save would be harmless-looking and wrong: it would put a date on a
    material whose price has never moved. It also costs a DOM write while somebody is typing."""
    p = ran["priceDate"]
    assert p["quietPatchNoRepaint"], "a name edit repainted the price date"
    assert p["quietPatchStillBumpedVersion"], "the version stamp stopped being adopted"
    assert p["assemblySaveDoesNotRepaintItems"]


@needs_node
def test_the_pack_size_is_on_the_numeric_field_list(ran):
    assert ran["numericFields"] == ["unit_cost", "coverage", "buy_qty"]


@needs_node
def test_a_typed_number_reaches_the_model_as_a_number(ran):
    """EXECUTED THROUGH THE HANDLER, which is what the previous version of this test did not do.

    It asserted the contents of `NUMERIC_ITEM_FIELDS`. Deleting the ternary that CONSULTS that list
    left the array sitting there intact, so the test passed while every typed figure went into the
    model as a string — and that shipped to staging. A string "5" divides by luck and concatenates
    the first time anything multiplies it."""
    e = ran["itemEdit"]
    assert (e["buyQtyType"], e["buyQty"]) == ("number", 5)
    assert (e["costType"], e["cost"]) == ("number", 1200.5), "a pasted $1,200.50 must survive"
    assert (e["coverageType"], e["coverage"]) == ("number", 275)
    assert (e["vendorType"], e["vendor"]) == ("string", "Sika"), "text was coerced to a number"


@needs_node
def test_each_edit_is_queued_for_the_server_exactly_as_typed(ran):
    """The model gets the parsed number; the server gets the raw string, because `validate_item` is
    the single authority on what is acceptable and it does its own parsing."""
    e = ran["itemEdit"]
    assert e["queued"] == ["items:buy_qty", "items:unit_cost", "items:coverage", "items:vendor"]
    assert e["queuedRaw"] == ["5", "$1,200.50", " 275 ", "Sika"]


@needs_node
def test_the_duplicate_hint_appears_and_disappears_through_the_handler(ran):
    """Not by calling similarNames() — by typing, into ONE cell across three keystrokes. An earlier
    version of this used a fresh cell per edit, which made "the hint went away" true no matter what
    the handler did; the mutation that never removes the hint survived it."""
    e = ran["itemEdit"]
    assert e["hintShown"], "typing a name similar to an existing one showed no hint"
    assert e["hintRemovedWhenNoLongerSimilar"], "the hint stayed after the name stopped matching"
    assert e["hintNotDuplicatedOnRetype"], "a second hint stacked under the first"


# ── two people editing one assembly ───────────────────────────────────────────
@needs_node
def test_a_conflict_disarms_the_edit_that_was_still_queued(ran):
    """FOUND BY ADVERSARIAL REVIEW. The 409 handler emptied the pending body but left the debounce
    timer armed, so a keystroke made during the ~300ms the conflicting PATCH was in flight scheduled
    a write whose payload was then wiped. 600ms later it fired on nothing and threw BEFORE the try
    block: no request, no "Not saved", no trace — on a page with no Save button, and immediately
    after we had told the estimator to re-apply their change."""
    c = ran["conflict"]
    assert c["armedBeforeConflict"] == 1, "the fixture never re-armed the timer, so it proves nothing"
    assert c["bufferEmptied"], "the conflicting body would be re-sent over the winner"
    assert c["timerDisarmed"], "the re-armed timer survived the conflict repaint"
    assert c["noSecondRequest"] and c["noUnhandledError"]


@needs_node
def test_a_conflict_shows_the_other_persons_version_and_says_so(ran):
    c = ran["conflict"]
    assert c["screenRepainted"], "the screen kept showing a version the database disagrees with"
    assert c["toldTheUser"], "a silent redraw mid-edit is worse than the conflict"


@needs_node
def test_a_timer_that_fires_with_nothing_queued_is_a_quiet_no_op(ran):
    """The belt to that brace. Whatever else empties the buffer, the callback must not throw
    outside its try block and turn a dropped write into an unhandled rejection."""
    c = ran["conflict"]
    assert c["emptyTimerIsQuiet"] and c["emptyTimerSendsNothing"]


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
def test_one_line_item_is_one_row(ran):
    """Hanz, 2026-08-19: "divisions should be a label up top like before not on the row. Make one
    line item, one row."

    The picker used to render an always-open panel in every ITEMS cell — a search box, a "Divisions"
    label, a division select, a vendor select, and an expanded list of twelve results. One line item
    filled a tall block, and a column label sat in the data area where the header already labels
    things. Two assembly lines must produce two rows and no expanded list.

    Mutation: emit the results list unconditionally in pickerFor() instead of only for the open
    line."""
    lines = ran["lines"]
    assert lines["rowCount"] == 2, (
        "two line items rendered %s rows" % lines["rowCount"])
    assert lines["pickerStartsClosed"], (
        "the results list is rendered before anyone opened it, so every row is a tall block")
    assert lines["pickerHasNoInRowFilters"], (
        "a Divisions label or a filter dropdown is still inside the row")
    assert lines["primaryLineCount"] >= 6, "numeric/action cells lost their first-line wrappers"
    assert lines["deleteControlAligned"], "the delete icon no longer shares the first-line height"


@needs_node
def test_the_item_search_looks_at_the_name_the_division_and_the_vendor(ran):
    """Hanz's original ask: "The search option for the Items must be multi dimensional. Could be
    from name, divison or vendor or comibation of those."

    One box, three fields — which is why the filter dropdowns could go. The fixtures differ in both
    of the non-name fields (OPF is Epoxy / Sherwin-Williams, OPF Primer is Polished Concrete / Gone
    Supply Co), so a matcher reading only `name` would answer these identically: both names start
    "OPF".

    Mutation: drop the division or vendor term from itemMatches' haystack."""
    s = ran["itemSearch"]
    assert s["byName"] == ["OPF Primer"], s["byName"]
    assert s["byDivision"] == ["OPF Primer"], (
        "searching a DIVISION found %r — the division is not in the haystack" % (s["byDivision"],))
    assert s["byVendor"] == ["OPF"], (
        "searching a VENDOR found %r — the vendor is not in the haystack" % (s["byVendor"],))
    assert s["byCombination"] == ["OPF Primer"], (
        "a division word plus a name word should narrow, not find nothing: %r"
        % (s["byCombination"],))
    assert s["caseInsensitive"] == ["OPF"], "the search is case-sensitive"
    assert s["blankFindsEverything"] == 2, "an empty box should offer everything"
    assert s["nonsenseFindsNothing"] == []
    assert s["emptySearchSaysSo"], "no-matches renders an empty list instead of saying so"
    assert s["resultNamesDivisionAndVendor"], (
        "a result matched on division or vendor does not show which — the match looks arbitrary")
    assert s["resultsAreButtonsKeyedByItemId"], "results are not selectable by stable item id"


@needs_node
def test_the_picker_opens_only_the_line_being_edited(ran):
    """Closed, the box answers "which item is this line?". Open, it asks "which item do you want?"
    — with the query in the box rather than the current name, so a different product can be found
    without deleting thirty characters first.

    Mutation: key the open state off the line object instead of the open index, and every row
    expands at once."""
    s = ran["itemSearch"]
    assert s["closedShowsTheItem"] and s["closedHasNoResults"]
    assert s["openShowsResults"], "the open line shows no results"
    assert s["openShowsTheQuery"], "the open box shows the item name instead of what was typed"
    assert s["onlyTheOpenLineExpands"], (
        "opening one line's picker expanded another line's too")


@needs_node
def test_the_typed_query_never_reaches_the_server(ran):
    """`_item_search` rides on the line while somebody types, and patchSoon sends the whole lines
    array. The server rebuilds each line from known keys so this cannot corrupt data — but a save
    should not carry one screen's half-typed search string.

    Mutation: return the line unchanged from lineForSave()."""
    assert ran["itemSearch"]["savePayloadIsClean"] == [
        "coverage", "item_id", "roundup", "waste_pct"], (
        "the save payload carries the picker's scratch keys: %r"
        % (ran["itemSearch"]["savePayloadIsClean"],))


@needs_node
def test_the_two_rounding_modes_render_differently(ran):
    """A rounded line names the packs it buys; an unrounded one names the fraction it uses. If both
    read the same, the checkbox looks decorative."""
    assert ran["lines"]["firstQtyLabel"] == "11 Gal"
    assert ran["lines"]["secondQtyLabel"] == "10.45 Gallon"


@needs_node
def test_the_live_updater_writes_into_the_cells_the_row_actually_has(ran):
    """THE POSITIONAL CONTRACT. `refreshNumbers` avoids rebuilding the row — that is what keeps the
    caret in the coverage field somebody is typing in — so it writes tds[4] and tds[5] on a table
    built by a different function. Adding a column ahead of them puts the quantity in the waste box
    with no error anywhere."""
    lines = ran["lines"]
    assert lines["qtyIdx"] == 5 and lines["costIdx"] == 6, \
        "the rendered row moved its computed cells: %s" % lines
    assert lines["indexesAgree"], (
        "refreshNumbers writes %s but the row's qty/cost cells are at %s"
        % (lines["updaterIndexes"], [lines["qtyIdx"], lines["costIdx"]]))


@needs_node
def test_the_live_updater_puts_the_quantity_and_the_cost_in_the_right_columns(ran):
    """EXECUTED, and the reason the test above is not enough.

    Its predecessor scraped `var QTY_TD = 4, COST_TD = 5;` out of the source and compared those
    numbers with the rendered column positions. Both agreed — and the two writes were transposed,
    so the constants were correct while `qtyLabel()` went into the Cost cell and the money went
    into Quantity. That shipped to staging: first paint looked right, then one keystroke in Coverage
    swapped them, and the estimator read a dollar amount out of the Quantity column.

    This runs refreshNumbers against the table renderPanel actually built and looks at where the
    content landed."""
    u = ran["liveUpdate"]
    assert u["untouchedBefore"], "the harness recorded writes before refreshNumbers ran"
    assert u["qtyCellGotTheQuantity"], "the Quantity cell did not get the quantity"
    assert u["costCellGotTheMoney"], "the Cost cell did not get the cost"
    assert u["qtyCellHasNoDollarAmount"], "a dollar amount was written into the Quantity column"
    assert u["costCellHasNoUnitLabel"], "a unit quantity was written into the Cost column"


@needs_node
def test_the_live_updater_never_touches_the_cells_holding_inputs(ran):
    """Rebuilding those is exactly what refreshNumbers exists to avoid: it fires on every keystroke,
    and rewriting the field being typed in would move the caret to the end of it."""
    u = ran["liveUpdate"]
    assert u["inputCellsUntouched"], "Material / Coverage / Waste / Roundup were rewritten"
    assert u["deleteCellUntouched"]


@needs_node
def test_the_live_updater_reports_a_broken_line_rather_than_pricing_it(ran):
    u = ran["liveUpdate"]
    assert u["brokenSaysSoInTheQtyCell"] and u["brokenCostCellClearedInsideAlignment"] and u["brokenRowFlagged"]


@needs_node
def test_the_live_updater_recomputes_each_rounding_mode_separately(ran):
    """The fractional row must not inherit the rounded row's numbers — same material, same
    coverage, and the only difference is the checkbox."""
    u = ran["liveUpdate"]
    assert u["secondRowQty"] == "10.45 Gallon"
    assert u["totalWritten"] == "$1,831.84" and u["perUnitWritten"] == "$0.637"


@needs_node
def test_the_empty_state_spans_the_columns_that_now_exist(ran):
    assert ran["lines"]["placeholderColspan"] == ran["lines"]["tdCount"] == 8


@needs_node
def test_typed_text_resolves_to_a_material_or_to_nothing(ran):
    """Never a "closest" guess: silently picking the wrong primer is worse than saying no, because
    a wrong material still produces a plausible price."""
    p = ran["picker"]
    assert p["exact"] == "i2" and p["caseInsensitive"] == "i2" and p["trimmed"] == "i1"
    assert p["partialRefused"] is None, "a half-typed name was resolved to a material"
    assert p["unknownRefused"] is None and p["blank"] is None
