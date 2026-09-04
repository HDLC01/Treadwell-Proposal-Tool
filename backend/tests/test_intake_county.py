"""The county picker, on the live intake form.

Hanz, 2026-09-02: *"For the polish beta we want to use the existing intake form v1 (not the beta).
The v2 is just add it with the toggle buttons."* The county came with them. It belongs next to the
**Remodel tax** toggle rather than up with the project fields, because that toggle is the only
reason it is asked: Kansas taxes commercial remodel labour at the combined rate at the job site,
and Kyle's workbook hardcodes a flat 10% that is not a real rate anywhere in the state.

It is the THIRD copy of this control (`polish-intake.js`, `estimate-review.js`), which is why it
moved out into `js/county-picker.js` -- one module, mounted by the page, so this does not become a
fourth.

EXECUTED, NOT GREPPED. Every way this can break is invisible to a source read:

  * **The mount is guarded.** `index.js` calls `window.TWCounty ? ... : null`, so a script tag that
    is missing or ordered after the page script degrades to a hidden field rather than a dead form.
    A grep sees the guard; it cannot tell you which side of it the browser took -- and on the wrong
    side every assertion in this file would go quiet while still passing. So the harness loads
    `county-picker.js` and `index.js` in the page's own order and proves the control is alive.
  * **The module's own defences hide its own failures.** `load()` wraps the fetch in a try/catch
    that degrades to an empty table. During development this file's rows read zero for an hour
    because the harness's `TW` stub lacked `resolveApiBase` -- no throw, no log, and every row
    assertion below quietly agreed. A row count only means something if the fetch is proven to have
    happened, so `test_the_reference_table_is_actually_fetched` pins the path.
  * **Enter inside a search list sits inside a form whose submit handler navigates away.** Whether
    it is swallowed is a fact about `preventDefault` at runtime, per
    [[execute-the-renderer-not-its-source]] -- and per [[browser-walks-find-keyboard-bugs]], no
    unit test finds a keyboard bug without reaching for the keyboard.
  * **The load-bearing invariant is a DOM fact.** `#county-input` deliberately carries no `name`,
    so `TW.readForm` never sweeps a half-typed search into the draft and the intake blob the two
    Continue handlers save is byte-for-byte what it was before this feature existed
    (`test_beta_intake_routing.py::test_the_two_handlers_save_byte_for_byte_the_same_blob`).

`tests/js/beta-routing-harness.js` runs both real modules against a DOM stub, types into the real
search box, keys the real list, clicks the real rows, and reports what reached the draft.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

import reference_tax

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "beta-routing-harness.js"
PICKER = FRONTEND / "js" / "county-picker.js"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def county():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed -- read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])["county"]


# ---------------------------------------------------------------- it is actually running

@needs_node
def test_the_control_is_mounted_and_binds_its_own_listeners(county):
    """The guard took the live branch.

    Three listeners, all bound by the module itself inside `wire()`. If the script tag were absent
    from `index.html`, or placed after `js/index.js`, `window.TWCounty` would be undefined at mount
    time, the guard would hand back `null`, and the field would sit there inert -- while every
    other test in this file still passed, because an empty control answers "nothing happened" to
    all of them. This is the test that makes the rest mean something.
    """
    assert county["boot"]["inputListeners"] == 1, "the search box has no input listener"
    assert county["boot"]["keydownListeners"] == 1, "the search box has no keydown listener"
    # Two, not one: index.js binds its own document click for the address autocomplete, and the
    # picker adds its own. A count of 1 means one of them lost its bind.
    assert county["boot"]["documentClickListeners"] == 2


@needs_node
def test_the_reference_table_is_actually_fetched(county):
    """And from the endpoint that serves it.

    `load()` swallows its own failures by design, so "0 rows" and "the fetch never ran" look
    identical from the outside. Pinning the path is what separates them.
    """
    assert county["boot"]["fetched"] == 1
    assert county["boot"]["fetchedPath"] == "/api/reference/counties"


@needs_node
def test_the_endpoint_serves_the_shape_the_picker_reads():
    """The contract between `reference_tax` and the picker, checked against the real table.

    Written the obvious way first -- every row must carry all six keys -- and it FAILED, which
    is the useful part. The table has three shapes, and only two keys are on all of them:

      * A CITY has `remodel_rate` and NO `rate` (15 rows).
      * A KANSAS COUNTY has both (12 rows).
      * Another 20 COUNTY rows have `rate` and NO `remodel_rate` -- Missouri and the Kansas
        counties nobody has verified a remodel rate for yet.

    So this asserts what is actually promised: the identity keys always, and at least one of
    the two rates, because a row that quotes neither has nothing to say. What absorbs the
    asymmetry on the JS side is `c.rate == null` / `c.remodel_rate == null` in the picker
    (:217, :151), and `undefined == null` is true in JS, so a MISSING key takes the same branch
    as an explicit null. That is load-bearing rather than lucky, and the harness fixture copies
    all three shapes so the branches are exercised against data the endpoint really sends.
    """
    rows = reference_tax.list_tax_areas()
    assert rows, "the tax table is empty"
    for r in rows:
        missing = {"name", "state", "kind", "notes"} - set(r)
        assert not missing, "%s is missing %s" % (r.get("name"), sorted(missing))
        assert r["kind"] in ("city", "county")
        assert "rate" in r or "remodel_rate" in r,             "%s quotes no rate at all, so it can only render as a blank" % r["name"]


@needs_node
def test_a_kansas_county_rate_is_the_county_portion_and_not_the_combined_rate():
    """Which is why the two saved numbers differ, and why only one of them prices anything.

    Johnson County KS serves `rate` 1.475% and `remodel_rate` 7.975%. The first is the county's
    own levy; the second is state + county combined, and it is the one the remodel override
    writes into the sheet. Reading `rate` as "the sales tax rate at this job" would under-bill
    by the whole 6.5% state share. Nothing does today -- `county_tax_rate` is written and
    carried and never read for money -- and this test is here so that stays deliberate.
    """
    counties = [r for r in reference_tax.list_tax_areas("KS")
                if r["kind"] == "county" and r.get("remodel_rate")]
    assert counties, "no Kansas county carries a remodel rate"
    for r in counties:
        assert r["remodel_rate"] > r["rate"],             "%s: remodel %s should exceed the county portion %s" % (
                r["name"], r["remodel_rate"], r["rate"])
        assert r["remodel_rate"] == pytest.approx(r["rate"] + reference_tax.KS_STATE_RATE),             "%s: the combined rate is not the portion plus the state rate" % r["name"]


# ---------------------------------------------------------------- it stays out of the way

@needs_node
def test_nothing_picked_and_the_toggle_off_means_nothing_on_screen(county):
    """Including the Clear button, which only makes sense beside a pick."""
    assert county["boot"]["fieldHidden"] is True
    assert county["boot"]["clearHidden"] is True


@needs_node
def test_the_note_is_said_even_while_the_field_is_hidden(county):
    """So revealing it never flashes an empty line, and it says WHY it is inert.

    The precedent is the picker's own line on the estimate screen: state plainly that an input is
    not affecting the price rather than hiding it and leaving the estimator to guess.
    """
    assert "not affecting the price yet" in county["boot"]["note"]
    assert "occupied remodel" in county["boot"]["note"]


@needs_node
def test_the_remodel_tax_toggle_is_what_reveals_it(county):
    """Off -> hidden, on -> shown, off again -> hidden, through `renderConditions()`.

    One choke point on purpose. The field's visibility is a function of two things -- the toggle
    and whether a county is picked -- and computing it in two places is how they drift.
    """
    t = county["followsTheToggle"]
    assert t["hiddenWhileOff"] is True
    assert t["hiddenWhileOn"] is False
    assert t["hiddenAfterOffAgain"] is True


@needs_node
def test_the_note_names_the_toggle_and_is_re_said_when_it_flips(county):
    t = county["followsTheToggle"]
    assert t["noteChanged"] is True
    assert "no county picked" in t["noteOn"]
    assert "not affecting the price yet" in t["noteOff"]


# ---------------------------------------------------------------- searching and picking

@needs_node
def test_a_search_finds_the_county_and_labels_it_for_a_human(county):
    p = county["pick"]
    assert p["rowCount"] >= 1
    assert p["firstLabel"] == "Johnson County, KS", "the row does not read as a place"
    assert p["firstRate"] == "remodel 7.975%", "the row does not show the rate being picked"


@needs_node
def test_a_city_row_reads_as_a_city_and_not_as_a_county(county):
    """The distinction is money, not cosmetics.

    A city row carries the FULL combined rate for a job inside the limits; a county row is the
    county-only floor, correct on unincorporated land. Labelling Overland Park "Overland Park
    County" would be nonsense, and reading it as a county would suggest the wrong rate.
    """
    s = county["rowShapes"]
    assert s["cityLabel"] == "Overland Park, KS"
    assert "County" not in s["cityLabel"]
    assert s["cityRate"] == "remodel 9.35%"


@needs_node
def test_a_city_saves_no_tax_rate_because_the_table_serves_none(county):
    """The one pick that stores a null on purpose.

    City rows carry `remodel_rate` only, so `c.rate == null ? null : c.rate` (:217) writes null
    for all 15 of them -- via `undefined`, not an explicit null, which is the harder case for
    that guard to absorb. It is inert today: the remodel override prices off
    `county_remodel_rate`, and nothing reads `county_tax_rate` for money. Pinned so that if
    something ever does, this test names the 15 rows it would read null from.
    """
    s = county["rowShapes"]
    assert s["citySavedTaxRate"] is None
    assert s["citySavedRemodelRate"] == pytest.approx(0.0935),         "the rate that actually prices the remodel must survive"


@needs_node
def test_a_missouri_row_says_exempt_rather_than_showing_a_rate(county):
    """And saves `null`, which is an answer -- not a missing value.

    Missouri does not tax remodel labour the way Kansas does. A row showing 6.225% next to the
    word "remodel" would be quoting a sales-tax rate as a remodel rate.
    """
    s = county["rowShapes"]
    assert s["moLabel"] == "Jackson County, MO"
    assert s["moRate"] == "remodel labour exempt"
    assert s["moRemodelSaved"] is None, "Missouri must not carry a remodel rate"
    # The plain sales-tax rate is still saved -- it is the remodel rate that is absent.
    assert s["moTaxRateSaved"] == pytest.approx(0.06225)


@needs_node
def test_a_pick_writes_exactly_its_own_four_keys(county):
    """No more, no fewer.

    `TW.setState` is a shallow merge, so the picker owning four top-level keys is what keeps it
    from disturbing anything else in the draft. Per [[state-snapshot-trap]], a save that spread a
    stale snapshot would quietly undo whatever else had moved.
    """
    saved = county["pick"]["saved"]
    assert set(saved) == {"county", "county_tax_rate", "county_remodel_rate", "county_notes"}
    assert saved["county"] == "Johnson County, KS"
    # Two different numbers, deliberately: the county's own levy share, and the combined rate
    # that prices the remodel. See test_a_kansas_county_rate_is_the_county_portion above -- an
    # earlier version of this test asserted 7.975% for both, which would have passed against a
    # fixture and been wrong about the live table.
    assert saved["county_tax_rate"] == pytest.approx(0.01475)
    assert saved["county_remodel_rate"] == pytest.approx(0.07975)


@needs_node
def test_a_pick_does_not_disturb_the_cells_the_toggles_own(county):
    """The conditions write `cell_values`; the county writes its own four keys. Different maps."""
    assert county["pick"]["cellValuesIntact"] == "Yes"


@needs_node
def test_after_a_pick_the_box_shows_the_place_and_not_the_half_typed_search(county):
    p = county["pick"]
    assert p["inputShows"] == "Johnson County, KS"
    assert p["resultsClosed"] is True
    assert p["clearOffered"] is True


@needs_node
def test_the_note_after_a_pick_states_what_the_rate_applies_to(county):
    """Labour and markups, never materials -- the rule the workbook implements and never said."""
    note = county["pick"]["note"]
    assert "7.975%" in note
    assert "Johnson County, KS" in note
    assert "Never on materials" in note


# ---------------------------------------------------------------- the keyboard

@needs_node
def test_the_arrow_keys_move_the_cursor_and_do_not_scroll_the_page(county):
    k = county["keyboard"]
    assert k["arrowHandled"] is True, "ArrowDown is not handled, or is not prevented"


@needs_node
def test_enter_in_the_list_chooses_a_row_and_never_submits_the_form(county):
    """THE ONE THAT WOULD HURT.

    The search box lives inside the intake `<form>`, whose submit handler saves and navigates to
    the estimate screen. An Enter that reached it would throw the estimator off the page
    mid-search, one keystroke into a county name.
    """
    k = county["keyboard"]
    assert k["enterPrevented"] is True
    assert k["navigatedAway"] == [], "Enter navigated away instead of choosing a row"
    assert k["chose"] == "Olathe, KS", "Enter did not choose the arrowed row"
    assert k["resultsClosed"] is True


@needs_node
def test_enter_with_nothing_arrowed_takes_the_top_match(county):
    """On a list narrowed to one row, Enter means that row -- not "arrow down first"."""
    e = county["enterTakesTopMatch"]
    assert e["prevented"] is True
    assert e["chose"] == "Wyandotte County, KS"
    assert e["nav"] == []


@needs_node
def test_escape_puts_the_box_back_to_what_is_saved(county):
    """An abandoned search must not leave the field naming a county the draft does not hold.

    Type "wyando" over a saved Olathe, press Escape, and the box has to read Olathe again -- or
    the screen and the bid disagree about where the job is.
    """
    e = county["escapeRestores"]
    assert e["picked"] == "Olathe, KS"
    assert e["after"] == "Olathe, KS", "Escape left a search string where the saved pick belongs"
    assert e["closed"] is True


# ---------------------------------------------------------------- clicking away, and clearing

@needs_node
def test_clicking_the_control_itself_does_not_close_it(county):
    """The document listener has to tell its own subtree from the rest of the page."""
    o = county["outsideClick"]
    assert o["stayedOpenOnItsOwnField"] is True
    assert o["keptTypingOnItsOwnField"] == "john"


@needs_node
def test_clicking_outside_closes_and_restores(county):
    o = county["outsideClick"]
    assert o["closedOnOutside"] is True
    assert o["restoredTo"] == "Sedgwick County, KS"


@needs_node
def test_clear_writes_the_absence_rather_than_leaving_the_rate_behind(county):
    """A cleared county has to clear its RATE too.

    This is the shape of the bug fixed in #442 on the estimate screen: the county went away on
    screen and its rate stayed in the draft, so the workbook billed a rate for a county nobody
    had chosen.
    """
    c = county["clear"]
    assert set(c["saved"]) == {"county", "county_tax_rate", "county_remodel_rate", "county_notes"}
    assert c["state"]["county"] == ""
    assert c["state"]["rate"] is None
    assert c["state"]["remodel"] is None
    assert c["state"]["notes"] == ""
    assert c["inputEmptied"] == ""
    assert c["clearHiddenAgain"] is True


@needs_node
def test_clearing_leaves_the_field_on_screen_while_the_toggle_is_on(county):
    """There is still a question to answer, so it stays where it can be answered."""
    assert county["clear"]["fieldHidden"] is False


# ---------------------------------------------------------------- coming back to it

@needs_node
def test_a_county_chosen_on_the_estimate_screen_shows_here(county):
    """Or the estimator picks it twice and the second pick is the one that counts.

    Both screens read and write the same four draft keys, which is the whole point of them being
    draft keys rather than page state.
    """
    h = county["hydrated"]
    assert h["inputShows"] == "Johnson County, KS"
    assert h["clearOffered"] is True
    assert "7.975%" in h["note"]


@needs_node
def test_a_picked_county_is_shown_even_with_the_toggle_off(county):
    """THE INVISIBLE-RATE HAZARD.

    Visibility is `remodel_tax OR hasPick()`, not `remodel_tax` alone. Hiding a picked county
    would leave a rate sitting in the draft with nothing on screen to account for it -- and no way
    to clear it without turning on a toggle the job may not need.
    """
    h = county["hydrated"]
    assert h["fieldHidden"] is False
    assert "the Remodel tax toggle is off" in h["note"], \
        "it is shown but does not say why it is inert"


@needs_node
def test_hydration_is_a_read_and_never_a_write(county):
    """Boot must not re-save what boot just loaded.

    Counted on the county keys rather than on the save log itself, so an unrelated boot save
    cannot make this pass or fail by accident.
    """
    assert county["hydrated"]["countySaves"] == 0


# ---------------------------------------------------------------- when the table is not there

@needs_node
def test_losing_the_reference_table_costs_the_search_its_rows_and_nothing_else(county):
    """The table is not the draft.

    A failed fetch has to leave the rest of the intake form working -- the toggles still save, the
    named fields are still there -- because a county is one line of a bid and the form is the whole
    of it.
    """
    f = county["fetchFailed"]
    assert f["rows"] == 0
    assert f["togglesStillSave"] is True
    assert f["formStillUsable"] is True


@needs_node
def test_a_dead_table_says_no_match_rather_than_going_blank(county):
    """A search box that answers nothing reads as broken. It should answer "nothing"."""
    assert "No county matches" in county["fetchFailed"]["resultsHtml"]


# ---------------------------------------------------------------- the fallback rate

@needs_node
def test_the_kansas_fallback_rate_is_quoted_from_the_endpoint(county):
    """NOT written down a third time.

    The number already lives in `reference_tax.KS_STATE_RATE` and in `polish-bid-core.js`'s
    `RATES.KS_STATE`. `/api/reference/counties` serves it precisely so this picker can say it out
    loud without a third copy -- and a third copy is how the first two come to disagree.
    """
    note = county["stateFallback"]["note"]
    assert "%g%%" % (reference_tax.KS_STATE_RATE * 100) in note, note
    assert "0.065" not in PICKER.read_text(encoding="utf-8"), \
        "the picker has its own copy of the Kansas rate"


@needs_node
def test_without_the_rate_the_sentence_drops_the_figure_instead_of_inventing_one(county):
    """The counterexample that makes the test above mean something.

    If the picker had the number hardcoded, both of these notes would read the same and both
    assertions would pass while proving nothing -- exactly the vacuous pair
    [[vacuous-invariant-needs-a-counterexample]] is about. They differ, so the figure really is
    coming from the endpoint.
    """
    with_rate = county["stateFallback"]["note"]
    without = county["stateFallbackAbsent"]["note"]
    assert with_rate != without, "the figure is not coming from the endpoint"
    assert "%" not in without, "a rate was invented with none served: %r" % without
    # Still a usable sentence -- it names the fallback, just not its size.
    assert "Kansas state rate" in without


# ---------------------------------------------------------------- the invariant

@needs_node
def test_the_search_box_is_not_a_form_field(county):
    """THE LOAD-BEARING FACT OF THIS WHOLE FEATURE.

    `#county-input` carries no `name`, so it never joins `form.elements` and `TW.readForm` never
    sweeps a half-typed "john" into the draft as project data. Give it a name and the intake blob
    changes shape, and
    `test_beta_intake_routing.py::test_the_two_handlers_save_byte_for_byte_the_same_blob`
    starts depending on what somebody happened to be typing when they pressed Continue.
    """
    assert county["boot"]["inputIsAFormField"] is False
    assert county["boot"]["namedFieldCount"] > 0, "the harness found no named fields at all"
