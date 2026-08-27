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
def test_the_division_cell_offers_every_division(ran):
    """Was test_division_is_a_checkbox_group_of_the_three_divisions. REWRITTEN, not deleted:
    the control is no longer a stack of checkbox labels.

    Hanz, 2026-08-24: "For the [divisions] can we have it in just one row? Also instead of a
    checkbox please pick a better UI that allows a material to have multiple divisions but they
    show up in one row." The old markup this used to pin (`class="division-picks"`, a bare
    `<label><input type=checkbox>` per division) made every row of the table three lines tall.
    What has NOT changed is the list it offers, so that half of the old assertion stays exactly
    as it was."""
    assert ran["items"]["hasDivisionChips"]
    assert ran["items"]["divisionOptions"] == [
        "Polished Concrete", "Epoxy", "Gypsum Underlayment"]


# ── the division chips ────────────────────────────────────────────────
# Hanz, 2026-08-24, quoted in full above. Every check below runs the real divisionPick and the real
# onItemEdit; the width ones read the real stylesheet, because "it fits on one line" is a fact about
# pixels and the OLD control was already display:flex with flex-wrap:wrap. It stacked because the
# box was 170px wide, so asserting the flex properties alone would have passed on the bug.
@needs_node
def test_a_material_in_two_divisions_shows_both_chips_as_on(ran):
    """The complaint was the height of the row, not the data model: a material has always been able
    to sit in several divisions, and both have to READ as on at a glance. Case-folded, because the
    stored value is whatever somebody typed ("polished concrete" here) and the offered spelling is
    the curated one."""
    d = ran["divisions"]
    assert d["group"], "the strip is not a labelled group"
    assert d["onOff"] == [["Polished Concrete", True], ["Epoxy", True],
                          ["Gypsum Underlayment", False]], d["onOff"]
    assert d["noRadios"], "a radio would say these are mutually exclusive, which they are not"


@needs_node
def test_toggling_one_division_off_leaves_the_others_alone(ran):
    """Executed through the real handler, against a row parsed from the real rendered markup. The
    failure this guards is a handler that rebuilds the whole list from the input it was handed
    instead of reading the row, which would silently drop every other division."""
    d = ran["divisions"]["afterTurningEpoxyOff"]
    assert d["model"] == ["Polished Concrete"], d["model"]
    # The legacy single-value column keeps following the first division, as it did before.
    assert d["category"] == "Polished Concrete"
    assert ran["divisions"]["afterTurningTwoMoreOn"] == [
        "Polished Concrete", "Epoxy", "Gypsum Underlayment"]
    assert ran["divisions"]["canBeEmptied"], (
        "a material could not be left unfiled - clearing the last chip has to save an empty list")


@needs_node
def test_the_save_payload_is_exactly_what_it_was_before(ran):
    """The point of keeping a real checkbox is that the save path did not have to move. The handler
    still reads data-f="divisions" and data-div off the input that changed, and still queues one
    field-level body of {"divisions": [names]} against `items`."""
    assert ran["divisions"]["contractUnchanged"]
    assert ran["divisions"]["afterTurningEpoxyOff"]["queued"] == [
        'items {"divisions":["Polished Concrete"]}']


@needs_node
def test_a_division_added_on_the_administration_tab_becomes_a_chip(ran):
    """Divisions are NOT a fixed three - the Administration tab adds them and /api/library/divisions
    serves them - so the cell has to render an unknown name it has never seen. Escaped on the way
    out, because a division name is free text somebody typed."""
    d = ran["divisions"]
    assert d["customIsOffered"] == ["Polished Concrete", "Epoxy", "Gypsum Underlayment",
                                    # HTML-escaped, which is what the browser turns back into "&".
                                    "Sealer &amp; Traffic Coatings"], d["customIsOffered"]
    assert d["customIsEscaped"], "a division name is injected into the row unescaped"
    assert d["customRendersAsOn"], "a custom division a material is IN does not read as on"
    # A name only an old item holds is offered back the same way an off-list vendor is, so deleting
    # a division on the Administration tab cannot make the items that used it uneditable.
    assert d["offListItemValueStillOffered"] == [
        "Polished Concrete", "Epoxy", "Gypsum Underlayment",
        "Terrazzo Restoration Systems"], d["offListItemValueStillOffered"]


@needs_node
def test_three_divisions_fit_on_one_line_and_more_wrap_instead_of_widening(ran):
    """ONE ROW - the whole request. The three real divisions have to sit side by side, and the
    column is capped so a fourth or a tenth wraps downwards instead of stretching the table
    sideways. At six that is two lines and at ten about four."""
    w = ran["divisions"]["width"]
    assert w["stripIsAFlexRow"] and w["chipIsInline"], (
        "the chips are not laid out side by side with unbreakable labels")
    assert w["threeFitOnOneLine"], (
        "the three default divisions need about %spx and the cell only offers %spx, so the cell is "
        "still more than one line tall" % (w["neededForThree"], w["stripMin"]))
    assert w["cappedSoTheTableCannotStretch"], (
        "nothing caps the strip, so six divisions would widen the table instead of wrapping")
    assert w["sixWraps"] and w["tenWraps"]
    assert w["textClampChars"] >= 22 and w["textClampEllipsises"], (
        "a long custom name is clipped at %s characters - two divisions could truncate into "
        "looking like the same word (\"Gypsum Underlayment\" is already 19)" % w["textClampChars"])


@needs_node
def test_each_chip_is_a_real_control_with_its_state_exposed(ran):
    """KEYBOARD AND SCREEN READER. The chip is a checkbox drawn as a pill rather than a div with
    aria-pressed, so Tab, Space and the announced "checked, Epoxy" all come from the platform and
    the multi-select semantics cannot be mistaken for a radio group. The input is CLIPPED, not
    display:none or visibility:hidden, either of which would take it out of the tab order and leave
    the keyboard nothing to press."""
    s = ran["divisions"]["state"]
    d = ran["divisions"]
    assert d["everyChipIsACheckbox"], "the chips are not checkboxes, so nothing announces a state"
    assert d["everyChipHasAnAccessibleName"], (
        "a chip's accessible name is not its division, so it reads as an unnamed checkbox")
    assert d["markIsHiddenFromTheTree"], "the state mark would be read out as part of the name"
    assert d["everyChipCarriesItsFullNameInATitle"]
    assert s["inputIsClippedNotRemoved"], (
        "the checkbox is removed from the page rather than clipped - the chip is unreachable by Tab")
    assert s["focusRingOnTheFace"], "a focused chip shows no ring, so keyboard users lose their place"


@needs_node
def test_the_on_state_is_not_colour_alone(ran):
    """Somebody who cannot separate the on-colour from the off-colour must still be able to count
    the divisions a material is in, so the mark inside the chip changes SHAPE as well: a tick when
    it is on and a plus when it is not. CSS content keyed off :checked rather than markup, because
    a click must NOT re-render the row - rebuilding the cell would throw away the focus the
    estimator just tabbed into."""
    s = ran["divisions"]["state"]
    assert s["onHasItsOwnFill"], "the on chip has no fill of its own"
    assert s["offMark"] and s["onMark"], "one of the two states has no mark at all"
    assert s["offMark"] != s["onMark"], (
        "both states draw %r, so the only difference is the colour" % s["onMark"])
    assert s["oldCheckboxStyleGone"], (
        "the old .division-picks stack is still in the page - two controls for one field")


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

# ══ confirming an Item change ════════════════════════════════════════════════
# Hanz, 2026-08-25: items "will be connected to many assemblies and an accidental change could
# alter the pricing." Every one of these runs through the REAL patchSoon — a test that called
# confirmItemPatch directly would still pass with the call site deleted, which is the failure this
# whole feature consists of.


@needs_node
def test_an_item_change_is_confirmed_before_it_is_sent(ran):
    """One dialog, naming the item and quoting the field that moved.

    It quotes before → after rather than saying "are you sure": the estimator is being asked about
    a number, and a dialog that does not show the number is one they can only answer by trusting
    the click they already made."""
    g = ran["itemConfirm"]
    assert g["errors"] == []
    assert g["asked"] == 1, "the save was sent without asking, or asked more than once"
    assert g["title"] == "Save this change?"
    assert g["name"] == "Densifier", "the dialog does not say which item"
    assert g["detail"] == "Cost:  42  \u2192  58", g["detail"]
    assert g["confirmText"] == "Save change", (
        "confirmDanger defaults its button to 'Delete', which is the wrong verb and the wrong "
        "promise for a save")
    assert g["tone"] == "warn", "danger tone is for destruction; this is a save"
    assert g["requests"] == ["PATCH /api/library/items/i1"]
    assert g["costAfter"] == 58


@needs_node
def test_two_fields_edited_in_one_pause_ask_once(ran):
    """THE REASON THE DIALOG LIVES AT FLUSH TIME. onItemEdit is bound to both `input` and `change`,
    so asking on the raw event would ask once per character and twice over for a <select>.
    patchSoon already merges a row's fields across 600ms of quiet, so that is the grain the
    question belongs at: one dialog per row per pause, listing everything that moved."""
    g = ran["itemConfirmTwoFields"]
    assert g["asked"] == 1, "two fields in one quiet period produced %s dialogs" % g["asked"]
    assert g["title"] == "Save these changes?", "the title did not pluralise"
    assert g["detail"] == "Cost:  42  \u2192  58\nVendor:  Sika  \u2192  Euclid", g["detail"]


@needs_node
def test_saying_no_sends_nothing_and_puts_the_value_back(ran):
    """The half that is easy to leave out, and worse than the bug it guards.

    A dialog that stops the PATCH but leaves the edit on screen means the row shows a price the
    server was never told about. Nothing marks it, a reload silently reverts it, and in between,
    anyone reading that item is reading a number that does not exist. So Cancel restores the
    snapshot taken before the first keystroke and repaints."""
    g = ran["itemCancel"]
    assert g["errors"] == []
    assert g["asked"] == 1
    assert g["requests"] == [], "Cancel still sent the change"
    assert (g["costAfter"], g["vendorAfter"]) == (42, "Sika"), (
        "the model kept the cancelled edit: %r" % ((g["costAfter"], g["vendorAfter"]),))
    assert g["repainted"] == "items,list,panel", (
        "the screen was not redrawn, so the cancelled value is still in the input: %r"
        % g["repainted"])
    assert g["neverSaidSaving"], "it announced 'Saving' for a save it then did not do"


@needs_node
def test_cancelling_a_division_toggle_restores_the_array(ran):
    """`divisions` is the one ARRAY field on an item, and it is mutated IN PLACE by the chip
    handler. A snapshot taken with Object.assign would share that array, so "before" would grow
    the new division along with the edit and Cancel would restore the exact value it was meant to
    undo — with the dialog still reporting success and nothing on screen wrong.

    This is the case that makes the copy in snapshotItem load-bearing rather than tidy."""
    g = ran["itemCancelArray"]
    assert g["asked"] == 1
    assert g["detail"] == ("Division:  Polished Concrete  \u2192  Polished Concrete, Epoxy"), g["detail"]
    assert g["divisionsAfter"] == ["Polished Concrete"], (
        "the cancelled division is still on the item: %r" % (g["divisionsAfter"],))


@needs_node
def test_a_value_typed_and_typed_back_is_not_asked_about(ran):
    """patchSoon merges a row's fields across the quiet period, so a value changed and then put
    back arrives in the payload identical to where it started. Asking about that teaches the
    estimator to dismiss the dialog without reading it, which costs more than the confirmation
    ever saves — so the comparison is against the snapshot, not against the payload existing."""
    g = ran["itemNoChange"]
    assert g["asked"] == 0, "it asked about a change that was not one"
    assert g["requests"] == ["PATCH /api/library/items/i1"], (
        "the save itself was dropped; a no-op payload is harmless and still gets sent")


@needs_node
def test_an_assembly_save_is_never_confirmed(ran):
    """The dialog is scoped to items on purpose. An assembly's lines are a takeoff somebody is
    actively building, where a dialog per pause would be unusable; an item is reference data that
    other records are priced from, which is the distinction Hanz drew.

    Read off the 409 scenario rather than its own run, because that one is a realistic assembly
    edit — two keystrokes, a conflict, a repaint — so a dialog leaking out of the items branch
    would have fired somewhere in it."""
    assert ran["conflict"]["neverAskedAboutAnAssembly"], (
        "the confirmation escaped the items branch and is now in front of assembly saves")

# ══ searching, copying, and a line nobody has filled in yet ══════════════════


@needs_node
def test_the_items_tab_can_be_searched(ran):
    """One box, reusing the matcher the assembly picker already searches with, so the two cannot
    disagree about what "opf primer" finds.

    No dropdowns beside it, deliberately. Division and vendor dropdown filters existed in the
    picker and were deleted on 2026-08-19 for three reasons that all still apply here: they made
    every row tall, Hanz asked for one matcher "not two dropdowns", and their state lived on the
    line object, so it was being PERSISTED to the server on every save — which is why lineForSave
    still strips underscore-prefixed keys."""
    g = ran["itemsSearch"]
    assert (g["unfiltered"], g["filtered"], g["missed"]) == (2, 1, 0)
    assert g["sameMatcherAsThePicker"], "the tab filters by a different rule than the picker"
    assert g["hits"] == "1 of 2 shown"
    assert g["hitsHiddenWhenNotFiltering"], "it reports a count when nothing is being filtered"
    assert g["badgeWhileFiltering"], (
        "the tab badge moved with the search, so filtering reads as materials disappearing")


@needs_node
def test_a_search_with_no_hits_does_not_offer_to_add_one(ran):
    """The empty state and the no-match state are different news and had one panel between them.
    "No materials yet" carries an Add button — offering that to somebody who has 40 materials and a
    typo in the box invites them to create the duplicate the rest of this work is about
    preventing."""
    g = ran["itemsSearch"]
    assert g["noMatchShown"], "a search with no hits showed nothing at all"
    assert g["emptyPanelStaysHidden"], "the 'add your first material' panel answered a bad search"
    assert g["noMatchHiddenOnAHit"], "the no-match panel showed alongside results"


@needs_node
def test_a_duplicate_is_named_the_way_hanz_asked(ran):
    """Hanz, 2026-08-25: "Densifier (2)". That diverges from the house format — `uniqueLabel` in
    estimate-review.js produces "Densifier copy 2" — and his wording wins on his page; the two
    lists never appear together.

    Counting starts at 2 because "(1)" reads as the first of a set and implies the original was
    renamed too."""
    g = ran["duplicateName"]
    assert g["first"] == "Densifier (2)"


@needs_node
def test_a_copy_of_a_copy_does_not_stack_suffixes(ran):
    """The stem is stripped of its trailing "(n)" before counting, or duplicating a copy gives
    "Densifier (2) (2)" and the one after that gives "Densifier (2) (2) (2)"."""
    g = ran["duplicateName"]
    assert g["ofACopy"] == "Densifier (2)", g["ofACopy"]
    assert "(2) (2)" not in g["ofACopy"]


@needs_node
def test_the_copy_counter_skips_names_taken_in_any_spelling(ran):
    """Collisions are compared through nameKey — case, spacing and punctuation dropped — because
    the SERVER's duplicate block normalises the same way. "Densifier(3)" and "Densifier (3)" are
    one name to it, so a counter that only avoided exact strings would hand back a name the save
    then refuses, which reads on screen as the Duplicate button being broken."""
    assert ran["duplicateName"]["skipsTaken"] == "Densifier (4)", (
        "the counter reused a name that is already taken in another spelling")


@needs_node
def test_a_line_with_no_material_yet_is_not_reported_as_broken(ran):
    """It used to arrive pre-filled with ITEMS[0] — whichever material sorts first alphabetically,
    carried in with its coverage. A real material, on a line nobody chose, pricing real money if
    it was left there.

    Starting blank exposes a second problem: "no material" and "the material was deleted" both
    reach the updater as missing_item, so a line added ten seconds ago announced "Item removed" in
    amber on a row flagged broken. That is a fault report about the estimator not having finished
    typing."""
    g = ran["blankLine"]
    assert g["saysPick"], "a blank line does not say what to do: %r" % g["qtyCell"]
    assert not g["saysRemoved"], "a line nobody filled in claims its material was removed"
    assert not g["flaggedBroken"], "an unfinished line is painted as a fault"


@needs_node
def test_a_line_whose_material_really_went_still_says_so(ran):
    """The other side of that, and the reason the two states are told apart by item_id rather than
    by the pricing reason: softening BOTH would hide a real broken line behind a friendlier
    message, and a broken line is the one thing on this page that must keep shouting."""
    g = ran["removedLine"]
    assert g["saysRemoved"], "a deleted material no longer reports itself"
    assert g["flaggedBroken"], "a genuinely broken line stopped being flagged"


# ── the redesign, 2026-08-27 ──────────────────────────────────────────
@needs_node
def test_new_assembly_left_the_page_header(ran):
    """Hanz, 2026-08-27: "I dont like the New assembly button up top."

    It sat in a .tabaction wrapper at the right-hand end of the tab strip, beside Administration
    and about thirteen hundred pixels from the rail it appends a row to, so the control you
    pressed and the row that appeared had no relationship on screen. Nothing is left in the strip
    now except the three tabs.

    Mutation: put any non-tab button back inside the tablist."""
    c = ran["createAction"]
    assert c["goneFromTheTabStrip"], "a control that is not a tab is still in the tab strip"
    assert c["oldNewRowWrapperGone"], (
        "#asm-newrow is still there - the second wrong home, below the whole two-column grid")


@needs_node
def test_the_create_control_sits_at_the_foot_of_the_list_it_adds_to(ran):
    """The rule that replaced it, in four places: materials, assemblies, and the three
    administration lists all end with a full-width row inside the same container, drawn like the
    rows above it. Press it and the new row appears where the control was.

    AFTER the list, not before: it has to read as the next row rather than as a header over the
    ones that already exist.

    Mutation: move #asm-new-2 above #asm-list."""
    c = ran["createAction"]
    assert c["inTheRail"], "New assembly is not at the foot of the assembly rail"
    assert c["materialsAddRowInTheCard"], "Add material is not inside the materials table's card"
    assert c["adminAddRows"], "an administration list has no add row of its own"
    # One shape, five uses (materials, assemblies, and three lists) - not a fifth way to draw a
    # card, which is the failure this page has form for.
    assert c["addRowCount"] == c["addBtnCount"] == 5, (
        "the add rows disagree in number: %s wrappers, %s buttons"
        % (c["addRowCount"], c["addBtnCount"]))


@needs_node
def test_the_rail_hides_as_a_whole_rather_than_just_its_list(ran):
    """EXECUTED through the real renderList. The create control is a child of the rail card now,
    so hiding only #asm-list - which is what the previous line did - would leave a New assembly
    button sitting alone in an empty box while the "No assemblies yet" panel offered a second one
    right beside it.

    Mutation: hide #asm-list instead of #asm-rail."""
    c = ran["createAction"]
    assert c["railShownWithAssemblies"] and c["railHiddenWithNone"]
    assert c["countStillPainted"] == 1, "renderList stopped painting the tab badge"


@needs_node
def test_the_materials_add_row_follows_its_table(ran):
    """Three states, and the add row belongs to only one of them. Under "No materials yet" it is
    the second Add button in a single card; under "Nothing matches that" it answers a typo with an
    invitation to create the duplicate the search just failed to find - which is the exact trap
    the two empty states were split apart to avoid.

    Mutation: leave #items-addrow visible unconditionally."""
    c = ran["createAction"]
    assert c["itemsAddRowWithRows"], "the add row is hidden when there are materials to add to"
    assert c["itemsAddRowWhenEmpty"], "the empty state offers two Add buttons at once"
    assert c["itemsAddRowOnNoMatch"], (
        "a search with no hits still offers to add one, which is how the duplicate gets created")


@needs_node
def test_the_controls_are_drawn_glyphs_not_typed_emoji(ran):
    """The house rule, and it is not taste. An emoji is rendered by whatever font the machine has
    installed, so the delete control is a different picture on Kyle's Windows box than on a phone,
    it cannot take the row's colour on hover, and it ignores every size and stroke token on the
    page. This one shipped with a trash can in three renderers and a stacked-squares character in
    a fourth.

    Read off the REAL rendered rows, so a glyph left behind in any one renderer fails."""
    ic = ran["icons"]
    assert ic["oldGlyphsGone"] and ic["noEmojiInRenderedRows"]
    assert ic["glyphCount"] == 4, (
        "expected duplicate, delete, list-delete and line-delete; found %s" % ic["glyphCount"])
    assert ic["allAreLucideShaped"], (
        "a glyph does not match the house geometry: 24 box, no fill, currentColor, width 2, round")
    assert ic["allHiddenFromTheTree"], (
        "the glyph is announced as well as the button, so the name gets read out twice")
    assert ic["deleteStillNamed"] and ic["duplicateStillNamed"] and ic["contractUnchanged"]


@needs_node
def test_the_glyph_cannot_swallow_the_press(ran):
    """THE HALF THAT IS EASY TO MISS, and it would ship looking perfect.

    Every one of these handlers reads its data- attribute off the element that was clicked. An
    <svg> inside the button IS that element over most of the button's area, and it carries no
    attribute - so the control would go dead everywhere except its padding, silently, with the
    hover state still working.

    Two independent answers, because either one alone is a tidy-up away from a control that looks
    right and does nothing: the stylesheet takes the glyph out of hit-testing, and the handlers
    resolve through closest() so they no longer care what was pressed.

    Mutation: drop either the pointer-events rule or any one closest() lookup."""
    ic = ran["icons"]
    assert ic["glyphIsNotAClickTarget"], "the SVG is still hit-testable inside its own button"
    assert ic["handlersResolveByClosest"], (
        "a delete or duplicate handler still reads its attribute off e.target")


@needs_node
def test_the_page_wears_the_apps_own_warm_palette(ran):
    """Settled 2026-08-25 after three rejected attempts, and this page was the screen still
    disagreeing with it. --surf:#f4f4f5 is a cool grey and --red:#c8102e is brighter than the
    brand red used anywhere else, so beside any other Treadwell screen this one read as somebody
    else's product. The tokens are now the ones in frontend/styles.css, read rather than invented.

    Mutation: put a cool grey back in --surf."""
    p = ran["palette"]
    assert p["red"] == "#9e001f" and p["redDark"] == "#6c0015" and p["redTint"] == "#ffdad8"
    assert p["surf"] == "#fbf9f8" and p["surfLow"] == "#f3eeed"
    assert p["ink"] == "#1a1a1a" and p["inkV"] == "#5c403f", (
        "--ink-v is the warm brown-grey, not a blue-grey")


@needs_node
def test_there_is_one_type_stack_and_one_radius_scale(ran):
    """Headings, buttons and the totals were set in system-ui while the prose explaining them was
    Inter, so a number and its own caption were different faces. And five corner radii were in use
    - 12, 10, 9, 8 and 7px - assigned by whichever value the last person happened to type.

    Mutation: add a font shorthand ending in system-ui, or a bare border-radius in px."""
    p = ran["palette"]
    assert p["uiStack"].startswith("'Inter'"), "the interface face is no longer the app's Inter"
    assert not p["systemUiLeftInAFontShorthand"], (
        "a font shorthand still names system-ui directly instead of going through --ui")
    assert p["radiiDeclared"] == ["12px", "8px", "6px"], p["radiiDeclared"]
    assert p["hardcodedRadii"] == [], (
        "a radius bypasses the scale: %s" % p["hardcodedRadii"])


@needs_node
def test_rounding_the_cards_does_not_clip_the_item_picker(ran):
    """CAUGHT WHILE BUILDING THIS, and it is the bug this page has already shipped once.

    The card clips its overflow so a full-bleed table head and the add row keep the rounded
    corners. But any overflow value other than `visible` is a clipping context, and the one thing
    on this page that deliberately escapes its box is the material picker's floating results - the
    whole reason the lines table is wrapped in .tw-nolimit rather than .tw. A clipped panel cuts
    that list off at the card edge, so the estimator sees two results out of twelve and the rest
    of the library looks missing.

    Mutation: drop the .card.apanel overflow:visible opt-out."""
    p = ran["palette"]
    assert p["cardClips"], "the card no longer clips, so the table head breaks its own corners"
    assert p["panelOptsOutOfClipping"], (
        "the assembly panel inherits the card's clipping and cuts off the picker's results")
    assert p["pickerIsInsideThePanel"], (
        "the picker moved out of the panel, so the opt-out is guarding the wrong box")


@needs_node
def test_no_renderer_emits_a_style_attribute(ran):
    """"Prefer classes to inline styles" - and the three renderers here were the worst offenders
    in the app, putting a width on every field they produced. They still size those fields; the
    sizes are classes now, so the stylesheet is where you go to change one.

    Mutation: put any style="..." back into renderItems, renderRefSection or renderPanel."""
    s = ran["inlineStyles"]
    assert s["inRenderedMarkup"] == [], s["inRenderedMarkup"]
    assert s["inThePage"] == [], s["inThePage"]
    assert s["nameFieldStillSized"] and s["costFieldStillSized"], (
        "the widths were deleted rather than moved to a class")


# ── filters and advanced search, 2026-08-27 ───────────────────────────
# Hanz: "For the Items and Assemblies under the Items Tab, we must have filters and an advanced
# search."
@needs_node
def test_a_bare_word_searches_exactly_what_it_used_to(ran):
    """THE COMPATIBILITY FLOOR, and it is load-bearing rather than polite. itemMatches is shared
    with the assembly line picker, so a grammar that changed what a plain word means would quietly
    change what an estimator finds when picking a material into a priced line.

    A bare word still means "appears somewhere in the name, the divisions or the vendor", and
    several bare words still narrow.

    Mutation: make an unscoped term search only the name."""
    a = ran["advSearch"]
    assert a["bareWordStillSearchesEverything"] == ["OPF"], (
        "a bare word stopped reaching the vendor field")
    assert a["bareWordsStillNarrow"] == ["OPF Primer"]
    assert a["blankStillFindsEverything"] == 2


@needs_node
def test_a_term_can_be_scoped_to_one_field(ran):
    """Both fixture materials are called OPF-something, so scoping is the only way to separate
    them by vendor - which is the whole point of the feature.

    THE ASSERTION THAT MATTERS IS scopeIsNotAFallback. "epoxy" is a DIVISION on the first
    material, so `name:epoxy` must find nothing. A scoped term that quietly falls back to the
    whole haystack when it misses looks like it works on every query anyone tries first.

    Mutation: have termHits ignore term.field."""
    a = ran["advSearch"]
    assert a["scopedToVendor"] == ["OPF"]
    assert a["scopedToName"] == ["OPF Primer"]
    assert a["scopedToDivision"] == ["OPF"]
    assert a["scopedToUnit"] == ["OPF", "OPF Primer"]
    assert a["scopeIsNotAFallback"] == [], (
        "name:epoxy matched a material whose NAME does not contain it - the scope is decorative")
    assert a["aliasesAgree"] == [["OPF"], ["OPF"], ["OPF Primer"]], (
        "div:, supplier: and material: do not agree with their long forms")


@needs_node
def test_a_cost_or_a_pack_can_be_compared(ran):
    """A price list is mostly numbers, and "what do we buy that costs over two hundred a pail" is
    not a question substring matching can answer at all.

    Mutation: drop the comparator branch and treat cost: as text."""
    a = ran["advSearch"]
    assert a["costGreaterThan"] == ["OPF Primer"] and a["costLessThan"] == ["OPF"]
    assert a["costAtLeast"] == ["OPF Primer"] and a["costExactly"] == ["OPF Primer"]
    assert a["packExactly"] == ["OPF Primer"], "pack: does not read buy_qty"
    assert a["priceIsAnAliasOfCost"] == ["OPF Primer"]
    assert a["toleratesDollarAndComma"] == ["OPF", "OPF Primer"], (
        "a figure copied off an invoice with its dollar sign and comma is rejected")


@needs_node
def test_a_term_can_be_negated_and_a_phrase_kept_whole(ran):
    """Two bare words narrow independently, so "opf primer" also matches a material called
    "Primer OPF". Quoted, it is one string in one order. And a price list is searched as often for
    what something is NOT - everything that is not epoxy - as for what it is."""
    a = ran["advSearch"]
    assert a["negatedBareWord"] == ["OPF Primer"]
    assert a["negatedScoped"] == ["OPF Primer"]
    assert a["negationCombinesWithTheRest"] == ["OPF Primer"], (
        "a negated term does not AND with the positive ones")
    assert a["phraseIsOneString"] == ["OPF Primer"]
    assert a["phraseInAScope"] == ["OPF Primer"], 'vendor:"gone supply" does not survive parsing'
    assert a["parsed"] == [
        {"neg": False, "field": "vendor", "value": "gone supply"},
        {"neg": False, "field": "unit_cost", "value": ">100"},
        {"neg": True, "field": "", "value": "epoxy"},
        {"neg": False, "field": "", "value": "loose"},
    ], a["parsed"]


@needs_node
def test_a_query_it_cannot_parse_matches_nothing_rather_than_everything(ran):
    """THE HONESTY RULE, and the one that is easiest to get backwards.

    The tempting implementation of an unparseable term is to discard it. That hands the whole list
    back, which does not look like an error - it looks like the search ran and everything matched.
    The estimator then scrolls a full price list believing they filtered it.

    So `cost:abc` matches nothing, and an unknown field name is searched as literal text rather
    than dropped. A material with NO cost recorded also fails every comparison, because absent is
    not zero and treating it as zero would file it under cost:<1 as though somebody had priced it
    at nothing.

    Mutation: `return true` for an unparseable number, or skip the term."""
    a = ran["advSearch"]
    assert a["nonsenseNumberFindsNothing"] == [], (
        "cost:abc handed back the full list, which reads as the filter being ignored")
    assert a["unknownFieldIsSearchedLiterally"] == []
    assert a["absentCostIsNotZero"] is False, "a material with no cost sorts as costing nothing"
    assert a["absentCostFailsGreaterThan"] is False
    assert a["blankIsNotZero"] is False
    # …but a scope somebody is still typing is not an error, it is a keystroke.
    assert a["halfTypedScopeShowsEverything"] == 2, (
        "typing vendor: blanks the table on the way to vendor:s")


@needs_node
def test_the_three_facets_narrow_the_way_a_faceted_list_should(ran):
    """OR within a facet, AND across them. Division is a list because "epoxy or gypsum" is the
    question actually asked; vendor is an exact match on a value the dropdown offered, not a
    substring, or picking Sika would also pull in a differently-named account that contains it.

    Mutation: AND the divisions together, or make the vendor a substring test."""
    f = ran["facets"]
    assert f["nothingOnShowsEverything"] == 4
    assert f["oneDivision"] == ["Priced", "No cost"]
    assert f["twoDivisionsOr"] == ["Priced", "No cost", "Gyp bag"], (
        "two divisions narrowed instead of widening - the facet ANDs with itself")
    assert f["divisionIsCaseInsensitive"] == ["Priced", "No cost"]
    assert f["oneVendor"] == ["Priced", "No cost"]
    assert f["vendorIsCaseInsensitive"] == ["Priced", "No cost"]
    assert f["facetsAnd"] == ["No cost"], "two different facets widened instead of narrowing"
    assert f["textAndsWithFacets"] == ["Priced"], "the search box does not combine with a facet"
    assert f["impossibleCombination"] == []


@needs_node
def test_the_condition_facet_finds_what_is_not_safe_to_price_from(ran):
    """THE FACET THAT EARNS THE BAR. Division and vendor only narrow what somebody could already
    find by typing a word. These answer the question no search can: what in this list will quietly
    produce a wrong bid.

    A material with no cost prices every assembly built on it at nothing, silently, and before
    this there was no way to go looking for one. The other three are the same shape of question -
    unfiled, unsourced, and never actually priced.

    Mutation: make no_cost accept a zero cost as priced."""
    f = ran["facets"]
    assert f["missingACost"] == ["No cost"]
    assert f["notInAnyDivision"] == ["Unfiled"]
    assert f["noVendor"] == ["Unfiled"]
    assert f["priceNeverRecorded"] == ["No cost", "Unfiled"]


@needs_node
def test_there_is_no_waste_or_roundup_facet_because_an_item_has_neither(ran):
    """Both were floated as candidates. Neither is a property of a MATERIAL: waste_pct and roundup
    are written by _clean_lines in backend/library.py and live on an assembly LINE, so the same
    material carries a different waste factor in every assembly that uses it.

    A facet for them on this tab would have to invent a value, which is the one thing a filter
    over real data must not do. Written down as a test so the next person to have the idea finds
    the answer instead of the shape of it."""
    f = ran["facets"]
    assert f["itemsHaveNoWasteOrRoundup"], (
        "an item now carries waste_pct or roundup - if that is real, this facet becomes possible")


@needs_node
def test_the_facets_belong_to_the_items_tab_and_not_to_the_matcher(ran):
    """The assembly line picker searches with the same itemMatches, deliberately, so the two boxes
    cannot disagree. It must NOT inherit the facets: a line unable to find a material because of a
    bar set on a different tab is unexplainable from where it happens, and the estimator would
    conclude the material had been deleted.

    Mutation: apply matchesFilters inside itemResultsHtml."""
    f = ran["facets"]
    assert f["pickerIgnoresTheFacets"], (
        "the line picker is being narrowed by the Items tab's filter bar")
    assert f["tabStillObeysThem"] == ["Priced", "No cost"]


@needs_node
def test_the_filter_survives_the_things_that_re_render_the_list(ran):
    """"The filter state must survive the things that re-render the list - an edit, a save, a tab
    switch back - or it will read as the filter randomly clearing itself."

    THREE MECHANISMS, and the third is the one that is easy to miss. The state lives in plain
    variables, not in the DOM. The controls live outside the tbody renderItems replaces. And
    renderFilterBar, which paint() calls on every edit and every save, compares the offered values
    before writing any markup - because rebuilding the chip strip on each pass would throw away
    the focus of anybody tabbing through it, which is a bug this project has shipped twice.

    Mutation: rebuild the chips unconditionally in renderFilterBar."""
    s = ran["filterState"]
    assert s["rebuiltFromTheModel"], "an active division did not come back ticked"
    assert s["chipWritesOnRepaint"] == 0 and s["vendorWritesOnRepaint"] == 0, (
        "renderFilterBar wrote its markup again on a repaint (%s chip writes) - in a browser that"
        " destroys every node in the strip and takes the focus with it"
        % s["chipWritesOnRepaint"])
    assert s["vendorHeld"] == "Sika" and s["conditionHeld"] == "no_cost"
    assert s["clearOffered"], "Clear filters is hidden while three facets are on"
    assert s["modelHeld"] == (
        '{"divisions":["Epoxy"],"vendor":"Sika","condition":"no_cost"}'), s["modelHeld"]


@needs_node
def test_the_clear_button_appears_only_when_something_is_on(ran):
    """It is the only thing on the bar that says a filter is active without being read carefully,
    so it must not be furniture that is always there."""
    s = ran["filterState"]
    assert s["clearHiddenWhenIdle"], "Clear filters is offered when nothing is filtered"
    assert s["clearOffered"], "Clear filters is missing while three facets are on"


@needs_node
def test_a_division_added_by_an_admin_becomes_filterable(ran):
    """The guard that stops renderFilterBar rewriting its markup must not stop it rewriting when
    the offered values genuinely changed, or a division added on the Administration tab cannot be
    filtered on until somebody reloads the page.

    And the rebuild has to keep whatever was already on, or adding a division silently drops the
    estimator's current filter.

    Mutation: return early from renderFilterBar before the signature comparison."""
    s = ran["filterState"]
    assert s["quietWhenNothingChanged"] == 0, "the strip is rewritten when nothing changed"
    assert s["writesAfterANewDivision"] == 1, (
        "adding a division did not rebuild the strip exactly once (%s writes)"
        % s["writesAfterANewDivision"])
    assert s["newDivisionAppears"], "a newly added division never reaches the filter chips"
    assert s["rebuildKeptTheActiveOne"], (
        "rebuilding the strip dropped the division that was already switched on")
    assert s["customIsEscaped"], "a division name is free text and is not being escaped"


@needs_node
def test_the_empty_state_says_what_it_left_out_and_offers_the_way_back(ran):
    """A blank table is the worst outcome a filter can produce, because the estimator cannot tell
    a filter that went too far from a library that is missing something.

    So the panel names every active constraint - the query, the divisions, the vendor and the
    condition - and carries a Clear filters button of its own, because somebody staring at no rows
    looks for the way out next to the nothing, not back up in the bar.

    Mutation: drop a constraint from filterSummary, or the panel's own clear button."""
    e = ran["filterEmpty"]
    assert e["panelShown"]
    assert e["namesTheQuery"] and e["namesTheDivision"] and e["namesTheVendor"] \
        and e["namesTheCondition"], e["why"]
    assert e["why"] == (
        'No materials matching "primer", in Gypsum Underlayment, from Sika, '
        "with no cost recorded."), e["why"]
    assert e["clearOfferedInThePanel"], (
        "the way back is only in the bar, above a table that has nothing in it")
    assert e["hitHidesThePanel"] and e["hits"] == "1 of 2 shown"
    assert e["badgeIsStillTheTotal"] == 2, (
        "the tab badge follows the filter, so materials read as having been deleted")


@needs_node
def test_a_facet_alone_counts_as_filtering(ran):
    """FOUND WHILE WIRING THIS UP. The line deciding whether to show the no-match panel read only
    the search box, which was right when the search box was the only filter. With a facet on and
    the box empty, narrowing to a division nothing is filed under produced a table with no rows,
    no add row (it hides with the rows), and no panel - a blank card with nothing anywhere saying
    why.

    Mutation: put `!!String(itemQuery).trim()` back in place of anyFilterActive()."""
    e = ran["filterEmpty"]
    assert e["facetAloneOpensThePanel"], "a facet with an empty search box shows a blank card"
    assert e["facetAloneExplainsItself"] == "No materials in Nothing Is In Here."
    assert e["addRowGoneWhenNothingMatches"]


@needs_node
def test_the_filter_controls_are_reachable_and_clearable_from_the_keyboard(ran):
    """Every facet is a real control - checkboxes and two selects - so Tab and Space and the
    announced state come for free, and the chip strip is a labelled group rather than a row of
    unnamed boxes.

    Escape clears the search box. type="search" grows a native clear affordance in Chromium, but
    it is a mouse target and Escape is not wired to it the same way everywhere; this is also the
    key that closes the item picker two tables over, so the page answers Escape consistently."""
    k = ran["filterKeyboard"]
    assert k["escapeClears"], "the search box cannot be cleared without a mouse"
    assert k["divisionsAreCheckboxes"] and k["vendorIsASelect"] and k["conditionIsASelect"]
    assert k["chipStripIsALabelledGroup"], "the chip strip is an unnamed group"
    assert k["selectsHaveLabels"], "a facet select has no label, only a first option standing in"


@needs_node
def test_the_syntax_is_written_down_where_somebody_will_find_it(ran):
    """An advanced search nobody is told the grammar of is a secret, and a tooltip on a search box
    is not where anybody looks. The syntax sits under the box in the same muted prose the rest of
    the page explains itself in, and is tied to the input with aria-describedby."""
    k = ran["filterKeyboard"]
    assert k["tipsExist"], "the search grammar is not described anywhere on the page"
    assert k["tipsShowRealSyntax"], "the examples shown are not the syntax the parser accepts"


@needs_node
def test_the_filter_bar_is_not_a_sixth_card(ran):
    """This page draws four boxes with a fill and a border and does not need a fifth. The bar is a
    spacing container over the table it narrows; the table's own card gives the edge below it, and
    everything inside is vocabulary that was already here - the search box, .btn.ghost.sm, the
    muted prose, and the chip shape from the Division cell.

    Also the structural half of the survives-a-re-render answer: the controls sit ahead of the
    tbody renderItems replaces, so that function cannot reach them."""
    k = ran["filterKeyboard"]
    assert k["barIsNotACard"], "the filter bar grew a card of its own"
    assert k["controlsOutsideTheRenderedBody"], (
        "a filter control is inside the tbody renderItems rebuilds, so it will lose its state")
