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
    # Exit 0 with nothing printed is its own failure: node empties its event loop and leaves when a
    # scenario is still awaiting a dialog or a request that never came, so the JSON line is never
    # written. Saying so beats an IndexError on splitlines()[-1].
    assert proc.stdout.strip(), (
        "the harness exited cleanly and printed nothing — a scenario never settled:\n"
        + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the page says what it is ──────────────────────────────────────────
@needs_node
def test_the_page_is_called_items_and_assemblies(ran):
    assert ran["page"]["h1"] == "Items and Assemblies"
    assert ran["page"]["title"].startswith("Items and Assemblies")


@needs_node
def test_the_items_tab_no_longer_explains_itself(ran):
    """WAS test_each_tab_says_what_belongs_in_it, and it asserted the opposite. REWRITTEN RATHER
    THAN DELETED so the next reader finds a decision instead of a gap.

    Hanz, 2026-08-27, screenshotting it: "Remove these notes." The sentence was "Items are entered
    as we buy them. One row per thing on the invoice - the pack you order, and what that pack
    costs. A five-gallon pail is 5 - Gallon, priced as the pail." He is the person who uses this
    tab every day and does not need the pack convention explained above it every time he opens it.

    The other two panes keep theirs. They were not what he screenshotted, and neither Administration
    nor Assemblies is a tab anybody lives in - Assemblies in particular holds the same materials
    seen a second way, which is genuinely not self-evident from a table of numbers.

    Mutation: put the Items sentence back."""
    page = ran["page"]
    assert not page["itemsIntro"], (
        "the Items explainer is back - Hanz asked for it gone on 2026-08-27")
    assert page["assembliesIntro"], "the Assemblies pane lost its intro, which was not asked for"
    assert page["adminIntro"], "the Administration pane lost its intro, which was not asked for"
    # The CLASS stays, because two panes still use it. A rule with no caller is what to delete;
    # this is not one.
    assert page["paneintroStillUsed"] == 2, (
        "expected Assemblies and Administration to still carry .paneintro, found %s"
        % page["paneintroStillUsed"])


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
def test_the_assembly_says_whether_it_is_measured_in_SF_or_LF(ran):
    """Hanz, 2026-08-28: "Coverage per Unit - is there a way we can change it from SF and LF?"

    Three labels, all read off the assembly instead of a constant: the totals tile, the test-quantity
    label, and its suffix. Before this the page said "Price per SF" and "Test area / SF" over a cove
    assembly's linear feet.

    The `unit` column is not new - it has been persisted since the table existed and
    polish-estimate.js already reads it to stamp SF/LF onto a takeoff row. It had no editor, so every
    assembly said SF because the create call hardcoded it.

    Mutation: hardcode "SF" in any of the three writes."""
    u = ran["assemblyUnit"]
    assert (u["lfPerUnitLabel"], u["lfAreaLabel"], u["lfAreaSuffix"]) == (
        "Price per LF", "Test length", "LF"), (
        "an LF assembly is still being described in square feet: %s" % u)
    assert (u["sfPerUnitLabel"], u["sfAreaLabel"], u["sfAreaSuffix"]) == (
        "Price per SF", "Test area", "SF")
    assert u["lfSelectSynced"] == "LF" and u["legacySelectSynced"] == "SF", (
        "the select does not show the unit the assembly actually holds")


@needs_node
def test_choosing_LF_relabels_the_screen_and_changes_no_number(ran):
    """THE GUARANTEE THAT MAKES THIS SAFE. `priceAssembly` divides by whatever is in the one area
    input and has no notion of what it measures, so the same lines and the same quantity must cost
    the same whether the assembly calls itself SF or LF. If these ever diverge, a relabel has
    started moving money.

    It is also why per-line units were NOT built: they would need a second denominator, and the
    Polish bid page cannot express one (a takeoff row carries a single measurement), so the library
    and the bid would disagree while the cross-check between them stayed green.

    An off-list legacy value ("sqft") reads as SF rather than being echoed, so the words on screen
    keep describing the arithmetic that ran."""
    u = ran["assemblyUnit"]
    assert u["lfTotal"] == u["sfTotal"], (
        "the unit label changed the total: %s vs %s" % (u["lfTotal"], u["sfTotal"]))
    assert u["lfPerUnit"] == u["sfPerUnit"], (
        "the unit label changed the per-unit price: %s vs %s" % (u["lfPerUnit"], u["sfPerUnit"]))
    assert u["legacyReadsAsSf"] == "SF"


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


# ══ the Cancel bypass ════════════════════════════════════════════════════════
# The dialog could be answered "no" and the rejected value still reached the database.
#
# `noBtn.focus()` in shared.js blurred the input the estimator was typing in; a blurred input
# with an uncommitted value fires `change`; `change` is bound to #items-body — so the page
# re-entered onItemEdit WHILE ITS OWN DIALOG WAS OPEN, snapshotted the already-edited model, and
# queued a second patch. 600ms later that one compared before against after, found them equal,
# and PATCHed with no dialog at all. The screen said 42. The row said 58.
#
# The fix is not a guard bolted onto that sequence: the dialog now fires WHEN FOCUS LEAVES THE
# ROW, so by the time it opens there is no row input left to blur.


@needs_node
def test_cancelling_an_item_change_does_not_let_the_value_through(ran):
    """THE BYPASS, executed. Everything here runs through the real onItemEdit on the real
    patchSoon, and the re-entrant blur-change is fired from inside the dialog-open hook — which is
    the only ordering that can reach it, and the reason the harness's dialog stub had to stop
    resolving on a microtask before this could be written."""
    g = ran["itemBypass"]
    assert g["errors"] == []
    assert g["modelMidEdit"] == 58, "the edit never reached the model; the probe proves nothing"
    assert g["asked"] == 1, (
        "asked %s times — a second dialog means the re-entry got through" % g["asked"])
    # The claim, stated the way it matters: the number the estimator rejected was never sent.
    assert all("58" not in str(b) for b in g["sent"]), (
        "the cancelled value reached the wire: %r" % (g["sent"],))
    assert g["requests"] == [], "Cancel still sent a request"
    assert g["costAfter"] == 42, "the model kept the cancelled edit: %r" % g["costAfter"]
    assert g["confirmOpenAfter"] is None, (
        "itemConfirmOpen was left set, so every later keystroke on the page is now discarded")
    assert g["pendingAfter"] == 0, (
        "the cancelled edit is still queued and will go out on the next flush")


@needs_node
def test_the_dialogs_own_focus_move_cannot_retake_the_snapshot(ran):
    """The MECHANISM, separately from the outcome — because a fix that only stopped the second
    PATCH would leave the same trap one call site away.

    While the dialog is open, the tbody's `change` listener is a synthetic event nobody produced.
    The modal overlay traps every real input, so discarding it costs nothing, and NOT discarding
    it costs the snapshot: rememberItem runs against the already-edited model, and from then on
    "before" and "after" agree about a change that was refused."""
    g = ran["itemBypass"]
    assert len(g["reentries"]) == 1, "the probe did not re-fire the blur-change"
    r = g["reentries"][0]
    assert r["open"] == "i1", (
        "itemConfirmOpen was not set before the await, so onItemEdit has nothing to check")
    assert r["snapshotCost"] == 42, (
        "the snapshot was retaken off the already-edited model, which is what made before == "
        "after on the next flush and sent the rejected value with no dialog: %r"
        % (r["snapshotCost"],))
    assert r["pending"] == 0, "the re-entry queued a second payload behind the open dialog"
    assert r["armed"] == 0, "the re-entry re-armed the debounce timer behind the open dialog"


@needs_node
def test_a_second_rows_save_waits_for_the_open_dialog(ran):
    """Two of these modals at once is one dialog trapping the focus the other one needs, over a
    question that names neither row clearly. So a flush defers while any item dialog is open — and
    it DEFERS rather than dropping, because the second row's edit is still on screen and still
    unsaved.

    The state is built through patchSoon rather than by typing, because typing into a second row
    while a dialog is up is unreachable: the overlay traps the input and the guard discards
    anything that gets past it. What IS reachable is a timer left armed by an earlier deferral,
    which is what this constructs."""
    g = ran["itemDialogQueue"]
    assert g["errors"] == []
    assert g["whileOpen"]["asked"] == 1 and g["whileOpen"]["forRow"] == "Densifier"
    assert g["askedWhileOpen"] == 1, (
        "a second dialog stacked on top of the first: %s were open" % g["askedWhileOpen"])
    assert g["secondStillQueued"], "the second row's edit was dropped instead of deferred"
    assert g["secondRearmed"], "it deferred without re-arming, so that edit would never be sent"
    assert g["askedInTheEnd"] == 2, "the second row was never asked about at all"
    assert g["secondAskedAbout"] == "Hardener", g["secondAskedAbout"]


@needs_node
def test_a_dialog_that_throws_is_a_cancel_not_a_dropped_write(ran):
    """If the await escapes the flush, the damage is not one lost edit. The payload has already
    left pendingPatch, the snapshot has already been consumed, and itemConfirmOpen is left SET —
    so onItemEdit's guard then swallows every keystroke on the page for the rest of the session,
    silently, with nothing on screen to explain it."""
    g = ran["itemDialogThrew"]
    assert g["errors"] == [], "the rejection escaped as an unhandled error: %r" % (g["errors"],)
    assert g["requests"] == [], "a dialog that never answered was treated as a Yes"
    assert all("58" not in str(b) for b in g["sent"]), g["sent"]
    assert g["costAfter"] == 42, "a broken dialog left the unconfirmed edit on the row"
    assert g["confirmOpenAfter"] is None, (
        "itemConfirmOpen survived the throw, so the page now discards every edit")


@needs_node
def test_cancel_does_not_restore_the_servers_own_timestamps(ran):
    """`updated_at` and `cost_updated_at` are the SERVER's to set — adoptSaved copies them off a
    successful write, and `cost_updated_at` only moves when the cost really changed.

    A snapshot taken before that reply landed holds the old stamps, so restoring the whole
    snapshot on Cancel throws away what the server just told us: the Dates cell goes back to
    quoting a price date the database has already moved past, and nothing marks it."""
    g = ran["itemCancelStamps"]
    assert g["errors"] == []
    assert g["asked"] == 1
    assert g["costAfter"] == 42, "the cancelled cost was not put back"
    assert g["stampsAfter"] == g["stampsBefore"], (
        "Cancel rolled a server-owned stamp back to the snapshot: %r, was %r"
        % (g["stampsAfter"], g["stampsBefore"]))


@needs_node
def test_cancel_puts_the_caret_back_in_the_field_it_was_typed_in(ran):
    """Cancel repaints the whole table, so the input the estimator was in stops existing. Without
    putting the focus back they are left on nothing, on a page whose only save trigger is leaving
    a row — so the next thing they type goes nowhere and the row they were correcting is two Tabs
    away."""
    g = ran["itemCancelStamps"]
    assert g["refocused"] == 1, (
        "the cancelled field was not refocused after the repaint (%r focus calls)" % g["refocused"])
    assert g["focusedElsewhere"] == [], (
        "the focus landed on a different field of the row: %r" % (g["focusedElsewhere"],))


@needs_node
def test_the_dialog_fires_on_leaving_the_row_not_on_a_typing_pause(ran):
    """Hanz, 2026-08-27. Two things at once, and they are the same change.

    The interruption: a dialog on a 600ms pause fires while the estimator is still in the row —
    mid-row, one field in, over an edit they have not finished making. Waiting for the row to be
    left means the question is asked once, about everything that moved.

    The bypass: when the dialog opens, focus has ALREADY left the row. There is no row input to
    blur, so nothing can fire a `change` and no re-entry is possible. That is why this is a fix
    at the root rather than a guard on the symptom."""
    g = ran["itemRowLeave"]
    assert g["errors"] == []
    assert g["duringTyping"]["asked"] == 0, "it asked while the estimator was still in the row"
    assert g["duringTyping"]["requests"] == 0, "it saved without asking while the row held focus"
    assert g["duringTyping"]["stillQueued"] == 1, "the edit was dropped rather than deferred"
    assert g["duringTyping"]["rearmed"] >= 1, (
        "the flush deferred without re-arming, so nothing will ever send this edit")
    assert g["afterASecondPause"]["asked"] == 0, "a second pause fired the dialog anyway"
    assert g["insideTheRow"]["asked"] == 0, (
        "tabbing between two cells of the SAME row counted as leaving it")
    assert g["askedOnLeaving"] == 1, (
        "leaving the row did not ask: %s dialogs" % g["askedOnLeaving"])
    assert g["detail"] == "Cost:  42  →  58\nVendor:  Sika  →  Euclid", g["detail"]


@needs_node
def test_a_dialog_somebody_else_put_up_holds_the_save_back(ran):
    """The route in is the row's own Remove button, and it only exists because of the row-leave
    timing. Clicking Remove leaves the focus INSIDE the row, so nothing flushes — and then the
    delete confirmation focuses its own Cancel button, which blurs that button and fires the
    focusout this page saves on. Two modals, one on top of the other, one of them asking about a
    material the other one is about to delete."""
    g = ran["itemOtherModal"]
    assert g["errors"] == []
    assert g["whileTheOtherIsOpen"]["asked"] == 0, (
        "a save question was stacked on top of the delete confirmation")
    assert g["whileTheOtherIsOpen"]["queued"] == 1, "the edit was dropped rather than held"
    assert g["whileTheOtherIsOpen"]["rearmed"] >= 1, "held without re-arming, so it is lost"
    assert g["askedAfterItClosed"] == 1, (
        "the held edit was never asked about once the other dialog closed")


@needs_node
def test_deleting_a_material_drops_the_edit_still_queued_for_it(ran):
    """Typing a cost and then reaching for that row's own Remove button never leaves the row, so
    under the row-leave rule the edit is still queued when the material stops existing. Left
    armed, that timer PATCHes a dead id — a 404 and "That change didn't save." about a row the
    estimator has just watched disappear."""
    g = ran["itemForgotten"]
    assert g["errors"] == []
    assert g["queuedBefore"] == 1, "the probe never queued anything, so it proves nothing"
    assert g["queuedAfter"] == 0, "the deleted row's edit is still queued"
    assert g["snapshotDropped"], "the deleted row's snapshot is still held"
    assert g["asked"] == 0 and g["requests"] == [], (
        "it still tried to save a material that no longer exists: %r" % (g["requests"],))
    assert g["calledOnDelete"], "the delete handler does not forget the row it just removed"


@needs_node
def test_the_item_dialog_asks_for_the_two_opt_ins(ran):
    """Both are about the bypass, not about looks.

    `focus:"container"` puts the focus on the dialog rather than on Cancel, so a stray SPACE — the
    key somebody hits to tick the checkbox they were aiming at — cannot press a button.
    `dismiss:"explicit"` drops the backdrop-cancels listener, so clicking the next cell cannot
    silently revert an edit the estimator meant to make. A save is not a deletion; the safe
    default for one is not the safe default for the other."""
    g = ran["itemAskedOpts"]
    assert g.get("focus") == "container", (
        "the item dialog still focuses the Cancel button: %r" % g.get("focus"))
    assert g.get("dismiss") == "explicit", (
        "a click outside still answers the question: %r" % g.get("dismiss"))


# ══ the shared dialog, EXECUTED out of shared.js ═════════════════════════════
# Nothing in this repo had ever executed confirmDanger, which is the second half of why the bypass
# survived review: `noBtn.focus()` reads as an accessibility nicety, not as the line that fires a
# `change` event on whatever the estimator was typing in.


@needs_node
def test_the_new_dialog_options_change_nothing_for_the_other_callers(ran):
    """Twenty-odd call sites across the frontend, four of them on this page. Both opt-ins default
    OFF and the assertion is made by running the SAME function with no options — not by reading
    the code and agreeing with it."""
    g = ran["confirmFocus"]
    assert g["defaultFocusesCancel"], "the default no longer focuses Cancel"
    assert g["defaultHasBackdropCancel"], "clicking the backdrop stopped cancelling"
    assert g["defaultBackdropCancels"], (
        "the backdrop listener is there but no longer resolves false")
    assert g["defaultTabindexAbsent"], "the dialog became focusable for callers that did not ask"
    assert g["defaultRestoresTheFocus"], "the default stopped putting the focus back"


@needs_node
def test_the_opted_in_dialog_focuses_itself_and_needs_an_explicit_answer(ran):
    """Focusing the dialog element instead of a button is the half that survives somebody moving
    the row-leave logic: even if a row input were still focused, nothing in the dialog reaches for
    a control inside the table.

    And it must stay closable. An inert backdrop with no keyboard route out is a trapped
    estimator, so Escape is asserted by what the promise resolves to."""
    g = ran["confirmFocus"]
    assert g["optedInFocusesTheDialog"], "it still focuses a button inside the dialog"
    assert g["optedInDialogIsFocusable"], (
        'the dialog was focused without tabindex="-1", so the browser will refuse it')
    assert g["optedInHasNoBackdropCancel"], "a click outside can still answer the question"
    assert g["bothTrapTheKeyboard"], "the focus trap was lost"
    assert g["escapeStillCancels"], "Escape stopped closing the dialog"
    assert g["optedInLeavesTheFocusAlone"], (
        "the dialog handed the focus back to whatever was active mid-focusout, which yanks the "
        "caret out of the field confirmItemPatch just restored")


@needs_node
def test_the_dialog_counts_how_many_of_itself_are_on_screen(ran):
    """TW.modalOpen() is what the Items page asks before putting a save question up, and it has to
    be a COUNT. Two dialogs can overlap — the delete confirmation's own focus move is what fires
    the focusout the Items page saves on — and with a boolean, the first of the two closing would
    report the second one gone and let a modal be stacked on top of it."""
    g = ran["confirmModalCount"]
    assert g["afterOne"] is True, "one open dialog did not register at all"
    assert g["afterTwo"] is True
    assert g["firstAnswered"], "Escape did not close the first dialog, so this measured nothing"
    assert g["secondStillWaiting"], "closing the first dialog answered the second one as well"
    assert g["afterClosingOne"] is True, (
        "closing one of two dialogs reported the screen clear — a boolean, not a count")
    assert g["afterClosingBoth"] is False, (
        "the count never came back down, so the Items page would defer every save from now on "
        "against a dialog that is not on screen")


@needs_node
def test_the_save_question_is_not_drawn_with_a_wastebasket(ran):
    """The icon slot is filled with textContent, so an SVG could not go through `icon` — and the
    warn tone's own default glyph is a wastebasket, over a dialog that says "Save this change?".

    `iconSvg` takes markup this page writes itself. It is never a project name, a vendor, or
    anything else a customer can type: the textContent path stays the only route for those."""
    g = ran["confirmIcon"]
    assert g["svgReachesTheSlot"], "the SVG did not reach the icon slot"
    assert g["svgNotWrittenAsText"], "the markup was also written as text and will render literally"
    assert g["warnDefaultUnchanged"], "a warn caller that passed no icon lost its glyph"
    assert g["dangerDefaultUnchanged"], "a danger caller that passed no icon lost its glyph"
    assert g["plainIconStillText"], "a caller passing `icon` no longer gets it as text"
    assert g["plainIconNotInjected"], (
        "`icon` is now injected as markup — that slot carries customer-typed names")


# ══ the name a new row is created under ══════════════════════════════════════


@needs_node
def test_add_material_picks_a_name_that_is_free(ran):
    """The button posted the literal "New material" every time. `create_item` refuses a duplicate
    name with a 400, so the SECOND press was dead — "Couldn't add that material. "New material" is
    already in the library." — and the only way out was to guess that renaming the first row would
    unstick it.

    Bare stem first: "New material (2)" as somebody's first material would be absurd."""
    g = ran["newMaterialName"]
    assert g["whenFree"] == "New material", g["whenFree"]
    assert g["whenTaken"] == "New material (2)", g["whenTaken"]
    assert g["whenTwoTaken"] == "New material (3)", (
        "the counter reused a name taken in another spelling — the server normalises punctuation "
        "and spacing the same way, so that name comes straight back as a 400: %r"
        % g["whenTwoTaken"])
    assert g["blank"] == "New material", g["blank"]


@needs_node
def test_the_administration_tab_picks_a_free_name_too(ran):
    """Identical literal default ("New vendor", "New division", "New unit") against the identical
    duplicate block. Uniqueness is per LIST, so a material called "New vendor" must not stop the
    Vendors tab adding one."""
    g = ran["newMaterialName"]
    assert g["refWhenFree"] == "New vendor", g["refWhenFree"]
    assert g["refWhenTaken"] == "New vendor (2)", g["refWhenTaken"]
    assert g["refDivision"] == "New division (2)", g["refDivision"]
    assert g["refIgnoresItems"] == "New vendor", (
        "the Vendors tab checked its default against the MATERIALS list: %r" % g["refIgnoresItems"])


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
    """The rule that replaced it, in four places: assemblies and the three administration lists
    all end with a full-width row inside the same container, drawn like the rows above it. Press
    it and the new row appears where the control was.

    AFTER the list, not before: it has to read as the next row rather than as a header over the
    ones that already exist.

    Materials is the exception (Hanz, 2026-08-28): its add row moved to the TOP of the card,
    because at the foot it was getting lost below the horizontal scrollbar and a full table of
    rows. New materials are unshifted to the front of the list to match, so pressing the button
    and seeing the result are still the same spot on screen — see
    test_the_materials_add_row_follows_its_table for the rest of that behaviour.

    Mutation: move #asm-new-2 above #asm-list."""
    c = ran["createAction"]
    assert c["inTheRail"], "New assembly is not at the foot of the assembly rail"
    assert c["materialsAddRowInTheCard"], "Add material is not above the materials table"
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
def test_the_search_hint_is_gone_and_nothing_is_left_pointing_at_it(ran):
    """WAS test_the_syntax_is_written_down_where_somebody_will_find_it, which asserted this line
    existed. REWRITTEN RATHER THAN DELETED, because a quietly vanished test reads as an accident.

    Hanz, 2026-08-27: "Remove these notes." The line said: Narrow it: vendor:sherwin, cost:>200,
    pack:5, "opf primer" for the whole phrase, or -epoxy to leave something out. Terms stack.

    THE GRAMMAR IS UNTOUCHED. Only the on-screen sentence went; every form it advertised is still
    parsed and is still covered by the five tests above this one. What was removed is the help,
    not the feature.

    THE ORPHAN THIS WOULD HAVE LEFT. The search input carried aria-describedby="search-tips",
    pointing at that paragraph's id. Deleting the paragraph and keeping the attribute leaves a
    reference to an element that does not exist, and the failure mode is silent: a screen reader
    announces no description at all rather than reporting a fault. The field keeps its aria-label,
    so it is still named.

    Mutation: leave the aria-describedby behind, or leave the .searchtips rules in the
    stylesheet."""
    k = ran["filterKeyboard"]
    assert k["tipsGone"], "the search-syntax hint is still on the page"
    assert k["noOrphanedDescribedBy"], (
        "aria-describedby survived the paragraph it pointed at - a dangling reference no screen "
        "reader will report")
    assert k["searchFieldStillNamed"], (
        "the search field lost its accessible name along with the hint")
    assert k["searchtipsCssGone"], (
        "the .searchtips rules are dead stylesheet now, and the only <code> they styled is gone")
    assert k["barClosedUp"], (
        "the bar still holds a row open where the sentence was - it spaces itself with gap, so "
        "deleting the child should have closed the space with it")


@needs_node
def test_the_filter_bar_still_reads_as_two_groups_without_the_sentence(ran):
    """A redesign that reads worse after a deletion is not finished.

    The syntax line was doing structural work nobody asked it to: it sat between the search box
    and the facets and separated them. With it gone the bar's row gap was 8px, the same distance
    as a facet's own label-to-control gap, so the query and the facets read as one undifferentiated
    block of controls.

    Retuned to 8px inside a facet, 12px between the bar's rows, 16px from the bar to the table.
    THE ORDERING is what is asserted, not the three numbers: each step has to be larger than the
    one it contains or the grouping stops being legible, and that relationship is what silently
    regresses when somebody nudges one value.

    Mutation: set the bar's row gap back to 8px, or make it wider than its own bottom margin."""
    h = ran["filterKeyboard"]["spacingHierarchy"]
    assert h["ordered"], (
        "spacing no longer nests: %spx inside a facet, %spx between rows, %spx to the table"
        % (h["inFacet"], h["betweenRows"], h["toTheTable"]))


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


# ── bulk add: a dozen materials in one go ────────────────────────────────────
# Hanz, 2026-08-28: "Will wants to add items in bulk from the Items list, but still being able to
# search and filter it out."
#
# The modal itself is not reachable from this harness — its DOM stub has no createElement, no focus
# and no checkbox — so the four DECISIONS were written as pure functions taking their state as
# arguments, and these test them directly against the real pricing engine. Open/close/focus is
# verified in a browser instead, the same position this file already takes with confirmDanger.


@needs_node
def test_the_bulk_picker_searches_the_same_way_every_other_box_on_the_page_does(ran):
    """Reuses `itemMatches`, so the bulk picker, the Items tab box and the per-line picker cannot
    disagree about what a query finds. Will is filtering a real library; three boxes with three
    behaviours would be worse than one box.

    Mutation: make bulkCandidates do its own substring test."""
    b = ran["bulkAdd"]
    assert b["findsByName"] == ["i2"], "a bare word stopped matching the name"
    assert b["findsByVendor"] == ["i1"], "the vendor: facet of the grammar is not reaching it"
    assert b["negationWorks"] == ["i1"], "negation is not reaching it"
    assert b["emptyQueryShowsAll"] == 2, "an empty query must show the whole library, not nothing"


@needs_node
def test_the_bulk_pickers_facets_are_its_own_and_do_not_move_the_items_tab(ran):
    """THE TRAP THIS AVOIDS, stated by the note on `visibleItems`: a picker silently narrowed by a
    bar on another tab. The modal draws its own facets, so it passes its own state and the Items
    tab's FILTERS must be untouched by anything the modal does.

    Mutation: have bulkCandidates read the module-level FILTERS."""
    b = ran["bulkAdd"]
    assert b["ownFacetNarrows"] == ["i1"], "the modal's own division facet did not narrow the list"
    assert b["itemsTabFiltersUnmoved"] == '{"divisions":[],"vendor":"","condition":""}', (
        "the modal moved the Items tab's filter state")


@needs_node
def test_select_all_speaks_about_what_is_on_screen(ran):
    """"All" has to mean all of what you can SEE. After typing a query, a control claiming
    everything is ticked while the visible list is half unticked is simply wrong — and ticks made
    before the search are still held, because narrowing a search must not silently untick what you
    already chose.

    Mutation: compute the state over the whole library instead of the shown ids."""
    b = ran["bulkAdd"]
    assert (b["allNone"], b["allSome"], b["allAll"]) == ("none", "some", "all")
    assert b["allOfTheShownOnes"] == "all", (
        "a tick outside the current search made the shown ones read as partial")
    assert b["emptyListIsNone"] == "none", "an empty list cannot be 'all'"


@needs_node
def test_a_bulk_added_line_prices_immediately_instead_of_arriving_broken(ran):
    """THE ONE THAT MATTERS MOST, and the reason bulkLinesFor is a function with a test rather than
    three lines in a click handler.

    `priceLine` reports a line with no coverage as `no_coverage`, and priceAssembly COUNTS that
    reason in `broken_lines`. So a bulk add that did not seed coverage from the item would drop
    twelve amber "Needs a coverage" rows into the assembly, and the estimator would reasonably
    conclude the feature was broken. The single-pick path has always seeded it; this matches it
    deliberately rather than by luck.

    Mutation: drop the coverage seed, or set it to null."""
    b = ran["bulkAdd"]
    assert b["lineCount"] == 2
    assert b["lineKeys"] == ["coverage", "item_id", "note", "role", "roundup", "waste_pct"], (
        "the bulk line shape drifted from what the single-pick path builds: %s" % b["lineKeys"])
    assert b["seededCoverage"] == [275, 275], "coverage was not seeded from the item"
    assert b["defaultWaste"] == [5, 5] and b["defaultRoundup"] == [True, True], (
        "a bulk-added row would save with different defaults than a hand-added one")
    assert b["allPriceable"], "a bulk-added line did not price"
    assert b["noneReportNoCoverage"], "a bulk-added line arrived as broken"
    assert b["firstQty"] == 11, "the priced quantity is not the one the engine gives"


@needs_node
def test_a_bulk_add_never_invents_a_blank_line(ran):
    """An id that no longer resolves — the material was deleted while the picker was open — is
    DROPPED rather than becoming a line with an empty item_id. The server drops such a line on save
    anyway (`_clean_lines` refuses one with neither item_id nor role), so keeping it would show a
    row that silently vanishes on the next load.

    An item with no coverage of its own is the opposite case: it still lands, and still says
    "Needs a coverage". That is an honest report about the material, not a fault in the add."""
    b = ran["bulkAdd"]
    assert b["unknownIdDropped"] == 1, "a ghost id became a line"
    assert b["noCoverageItemStillLands"] == 1, "an item with no coverage was silently refused"
    assert b["noCoverageItemSaysSo"] == "no_coverage"


@needs_node
def test_the_picker_knows_how_much_room_is_left_before_the_click(ran):
    """The server caps an assembly at 60 lines. It used to take the first 60 SILENTLY, which is
    defensible against a hostile 500-line payload and indefensible against a deliberate add of 40:
    ten materials would vanish under a 200 OK.

    Answering here lets the button explain itself while there is still something to change.
    Hanz, 2026-08-28, choosing this over raising the cap: keep 60, but refuse loudly.

    Mutation: return fits:true unconditionally, or drop the Math.max on room."""
    b = ran["bulkAdd"]
    assert b["maxIsTheServersCap"] == 60, (
        "BULK_MAX_LINES drifted from _MAX_LINES in backend/library.py")
    assert b["roomOnEmpty"] == {"used": 0, "room": 60, "over": 0, "fits": True, "max": 60}
    assert b["roomAt59"]["fits"] is True and b["roomAt59"]["room"] == 1
    assert b["roomAt59Over"]["fits"] is False and b["roomAt59Over"]["over"] == 1
    assert b["roomAt60"]["fits"] is False and b["roomAt60"]["room"] == 0
    # Already over the cap (a legacy row, or the cap lowered since): room clamps at zero rather
    # than going negative and reading as "room for -1 more".
    assert b["roomAt61"]["room"] == 0 and b["roomAt61"]["fits"] is False


# ── the save machinery cannot race itself ────────────────────────────────────


@needs_node
def test_a_second_save_waits_while_the_first_is_on_the_wire(ran):
    """THE RACE WAS AGAINST OURSELVES, not another person.

    Every successful PATCH bumps `updated_at`, and an assembly save declares the version it was
    editing so two people cannot silently overwrite each other. Those two facts together produced a
    self-conflict: save #1 left, save #2's timer fired 600ms later and read the SAME `updated_at`
    (`adoptSaved` has not run until #1 returns), went out, and the server correctly called it stale.
    `adoptConflict` then replaced the model wholesale, dropped the pending buffer, and told the
    estimator "Somebody else changed this while you had it open" — about nobody. Reachable by typing
    quickly on a slow connection, and with the bulk picker it could discard a whole batch of lines.

    WHY THE EXISTING CONFLICT SCENARIO DID NOT CATCH THIS: it fires the second timer only AFTER the
    reply is released, so a second flush never begins mid-flight and the guard is never reached.
    Verified by removing the guard and re-running: `onlyOneWhileOpen` and `editStillQueued` both go
    false, and BOTH requests carry the same stale stamp.

    Mutation: delete the `if (inFlight[key])` line in flush."""
    f = ran["inFlight"]
    assert f["onlyOneWhileOpen"], "a second PATCH went out while the first was still in flight"
    assert f["editStillQueued"] and f["stillArmed"], (
        "the second save was DROPPED rather than made to wait — the edit is still on screen")
    assert f["bothEventuallySent"], "the waiting save never got its turn"
    assert f["noUnhandledError"]


@needs_node
def test_the_waiting_save_carries_the_version_the_first_one_produced(ran):
    """The whole point, in one assertion. Waiting is only useful if what goes out afterwards is
    stamped with the version the first save created — otherwise the second request is still stale
    and still 409s, just later.

    T1 then T2, never T1 twice."""
    f = ran["inFlight"]
    assert f["firstCarriedTheOldVersion"] == "T1"
    assert f["secondCarriedTheNewVersion"] == "T2", (
        "the waiting save went out with the stamp the first one replaced (%s) — it would 409 "
        "against our own write" % f["secondCarriedTheNewVersion"])


@needs_node
def test_a_failed_save_does_not_silence_the_record_for_good(ran):
    """A lock that is never released is worse than the bug it fixes. `flush` returns early on a 409
    and on any non-ok status, so the release lives in a `finally` — without that, one failed save
    would stop that record ever saving again for the rest of the session, with the screen reporting
    nothing at all.

    Mutation: move the `delete inFlight[key]` out of the finally and onto the success path."""
    assert ran["inFlight"]["savesAgainAfterAFailure"], (
        "after a 500 the record never saved again — the in-flight lock was not released")
