"""The Markup page (frontend/markup.html + js/markup.js), executed out of the real renderer.

EXECUTED, NOT GREPPED. Every assertion below reads nodes that markup.js actually built, via
backend/tests/js/markup-page-harness.js. That is not a style preference: on 2026-08-12 the CRM
board went down on production with `ReferenceError: STAGE_CREATED is not defined` while the whole
suite was green, because every test read the renderer's source text and none of them ran it. A
source assertion also cannot tell a mention of ADMIN from a gate on it.

WHAT THIS PAGE MUST NOT DO -- the properties worth the harness:

  * **An ABSENT line must not read as a zero.** Gyp has no hard-bid rate: the workbook cell is
    EMPTY. backend/markup.py stores that as `applies=false, formula=NULL` and stores "this line
    prices to nothing" as `applies=true, formula='0'`, and the whole feature is shaped to keep
    those apart. Rendering the absent one as an empty editable box invites somebody to fill it
    in; rendering it as 0% reads as a discount that was declined. So the page renders a third
    state, and the Gyp scenario puts it on screen beside a genuine filed `'0'` on bond.
  * **A broken formula must never price as $0.00.** It reads "Unpriceable", and so does every
    line below it, and so does the total. That mirrors Kyle's own `Gyp!B75` `"error"` sentinel,
    and it is markup-core.js's stated safety property carried up into the screen. A markup line
    that silently drops to zero is a bid wrong in the customer's favour that nobody notices.
  * **A non-admin is shown nothing editable.** `_require_admin` in main.py is the real gate; this
    is only so nobody is handed a control that 403s. It fails closed -- ADMIN starts false and is
    settled before the first paint.
  * **The tabs come from the API.** Five sheet LAYOUTS, and deliberately no Combo: a combo job is
    two option lines each priced off its own tab, so markup.py refuses the string by name and a
    Combo tab here would offer to store a rate nothing could ever read.

AND, SINCE THE 2026-09-05 REDESIGN, three more:

  * **A line whose answer is one number gets one number box.** The page asked an estimator to
    hand-author `MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 22500,35%, 32500,32%, 30%))` to say
    what the GP rate is. Which control a row gets is READ OFF the stored formula, and the two
    genuinely banded lines get a ladder of typed numbers rather than a string.
  * **LOOKING AT A CONTROL MUST NOT FILE A RATE.** A ladder cannot be an empty box the way a
    single number can, so it is seeded from the built-in -- which means tabbing across it without
    typing must recompose to exactly what it was seeded with and send nothing. `roundTripPuts`
    is that assertion, and a mutation proves it can fail.
  * **The keyboard must survive the repaint.** Five bands is ten number boxes in one cell. A
    repaint on the way out of one steals the focus the person just tabbed into -- a bug this repo
    has shipped -- so the handler reads `ev.relatedTarget` and the walk below tabs and types.

The preview figures come from the REAL markup-core.js, and so does the parse the simple controls
are built on, so nothing here can pass against a stub that disagrees with what prices a bid.

Skipped when node isn't installed; it's on the dev box and in the Docker image.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

import markup

REPO = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = REPO / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "markup-page-harness.js"

# The three files the page is made of. Copied wholesale for the mutation runs below.
PAGE_FILES = ("markup.html", "js/markup.js", "js/markup-core.js")

# The two built-ins the ladders have to reproduce, written here independently of markup.js so a
# drift on either side is a failing test rather than a rate nobody chose.
GP_BANDS = "MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 22500,35%, 32500,32%, 30%))"
HARD_BID = ("IF(hard_bid_on, IF(subtotal>=60000, -4%, "
            "IF(local, IF(subtotal>=13000, -2.5%, 0), 0)), 0)")

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def drive(frontend: pathlib.Path):
    """Run the harness against a frontend directory and return its JSON."""
    proc = subprocess.run(["node", str(HARNESS), str(frontend)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed -- read this before assuming a product bug:\n" + proc.stderr)
    # Exit 0 with nothing printed is its own failure: node empties its event loop and leaves when
    # a scenario is still awaiting a request that never came, so the JSON line is never written.
    assert proc.stdout.strip(), (
        "the harness exited cleanly and printed nothing -- a scenario never settled:\n"
        + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    return drive(FRONTEND)


def mutate(tmp_path, old, new, expect_count=1):
    """Copy the page into tmp_path, swap `old` for `new` in markup.js, and drive THAT copy.

    Every guard below is proved by breaking it. A green "X iff Y" proves nothing if no fixture can
    make X and Y disagree, so each mutation test asserts the mutant behaves WORSE -- if the
    mutation changes nothing, the assertion it is defending was vacuous.
    """
    return drive(copy_page(tmp_path, old, new, expect_count=expect_count))


def copy_page(tmp_path, old, new, expect_count=1):
    """The copy-and-edit half of mutate(), for the one mutation that must not run clean.

    The edit is verified ON DISK before anything runs it. read_text() normalises CRLF, so a
    mutation whose `old` spans a line break silently matches nothing and the run then looks like
    a passing test defending nothing at all.
    """
    dest = tmp_path / "frontend"
    (dest / "js").mkdir(parents=True, exist_ok=True)
    for rel in PAGE_FILES:
        (dest / rel).write_text((FRONTEND / rel).read_text(encoding="utf-8"),
                                encoding="utf-8", newline="\n")

    target = dest / "js" / "markup.js"
    src = target.read_text(encoding="utf-8")
    assert src.count(old) == expect_count, (
        "the mutation's anchor is not in markup.js %d time(s) -- the source moved and this test "
        "is no longer proving anything: %r" % (expect_count, old))
    target.write_text(src.replace(old, new), encoding="utf-8", newline="\n")

    landed = target.read_text(encoding="utf-8")
    assert old not in landed, "the mutation did not land on disk"
    assert new in landed, "the mutation did not land on disk"
    return dest


def row(snap, line_key):
    for r in snap["rows"]:
        if r["line"] == line_key:
            return r
    raise AssertionError("no %r row was rendered; got %r" % (line_key, snap["rowOrder"]))


def parts(r):
    """A row's simple controls as {part: value} -- "value" for a one-number box, "edge-2"/"rate-2"
    for the third rung of a ladder."""
    return {i["part"]: i["value"] for i in r["inputs"]}


# ── the vocabulary is the backend's, not a second copy ────────────────
@needs_node
def test_the_rows_are_markups_own_chain_in_markups_own_order(ran):
    """markup.CHAIN pinned by rendering it.

    /api/markup/rules ships `layouts` and `line_keys` precisely so the editor cannot drift, but it
    does NOT ship CHAIN -- and CHAIN is what puts `contingency` and `remodel_tax` in their places
    between the editable lines, which is the only way a reader can see what a line's base is. So
    the page keeps one copy of it and this is where the two are compared. Order matters as much as
    membership: the chain COMPOUNDS, so a line in the wrong place is priced off the wrong base.

    Mutation: reorder or drop a line in markup.js's CHAIN."""
    assert ran["dayOnePolish"]["rowOrder"] == list(markup.CHAIN)


@needs_node
def test_the_editable_lines_are_exactly_the_api_line_keys(ran):
    """Editable == has a switch and a control. Read off the rendered rows, not off a list.

    markup.LINE_KEYS is CHAIN minus the two the backend refuses by name, and an admin offered a
    box for a line the API would refuse is being set up to collect a 400."""
    editable = [r["line"] for r in ran["dayOnePolish"]["rows"] if r["inputs"]]
    assert editable == list(markup.LINE_KEYS)


@needs_node
def test_the_tabs_are_the_five_sheet_layouts_from_the_api(ran):
    """Five LAYOUTS, in the API's order, off the API's own `layouts` array."""
    assert [t["layout"] for t in ran["dayOnePolish"]["tabs"]] == list(markup.LAYOUTS)
    assert len(markup.LAYOUTS) == 5


@needs_node
def test_a_combo_tab_cannot_appear_even_if_the_api_sends_one(ran):
    """A combo job is TWO option lines, each priced off its own tab.

    markup.py refuses the string `combo` by name, because a rate filed against a Combo tab could
    never be read by anything -- there is no combo layout in the workbook. The page filters it
    too rather than trusting the response, so a future API that starts shipping it renders a
    tab-strip a person can still use instead of a dead tab that silently stores nothing.

    The harness feeds `layouts: [polish, combo, seal, epoxy, leveling, gyp]`.

    Mutation: drop the filter (test_a_dropped_combo_filter_puts_a_combo_tab_on_screen)."""
    layouts = [t["layout"] for t in ran["poisoned"]["tabs"]]
    assert "combo" not in layouts
    assert layouts == list(markup.LAYOUTS)


@needs_node
def test_a_line_key_the_chain_has_never_heard_of_is_shown_not_swallowed(ran):
    """The API sends `escalation`; CHAIN does not have it.

    Appended rather than dropped, because a line silently missing from the chain is worse than one
    in the wrong place -- the total would be short and the screen would look complete. It has no
    built-in on this page, so it reads Unpriceable rather than guessing a rate -- and it still
    gets the one-number box, because "what is our rate?" is the question it is asking."""
    assert ran["poisoned"]["rowOrder"][-1] == "escalation"
    r = row(ran["poisoned"], "escalation")
    assert r["figure"] == "Unpriceable"
    assert parts(r) == {"value": ""}
    assert any("No built-in on this page for Polish" in n for n in r["notes"]), r["notes"]


# ── one number, one box ───────────────────────────────────────────────
@needs_node
def test_a_flat_rate_line_is_one_number_box_not_an_expression(ran):
    """THE REDESIGN, in one assertion. Superintendent & PTO is 2.7%; the control is a box you type
    2.7 into, with a % beside it, and nothing else.

    Mutation: test_a_simple_control_for_an_expression_it_cannot_hold_misrepresents_it proves the
    choice of control is read off the formula rather than assumed."""
    for line_key, built_in in (("super_pto", "2.7"), ("soft_costs", "16"), ("bond", "0")):
        r = row(ran["dayOnePolish"], line_key)
        assert r["advanced"] is False, "%s opened in the expression box" % line_key
        assert [i["part"] for i in r["inputs"]] == ["value"], (
            "%s has %r, not one number box" % (line_key, [i["part"] for i in r["inputs"]]))
        assert r["inputs"][0]["placeholder"] == built_in, r["inputs"][0]
        assert "%" in r["rateText"], "the number box has no unit beside it: %r" % r["rateText"]


@needs_node
def test_the_box_is_empty_and_the_constant_is_only_a_placeholder(ran):
    """Prefilling a one-number box with a value that is not stored would be a lie about state, and
    the first blur would save it as though somebody had chosen it.

    A LADDER IS THE EXCEPTION, and deliberately: ten blank boxes with placeholders would mean
    filling all ten in to change one, so it is seeded and its note says the numbers are the
    built-in's -- see test_every_built_in_ladder_round_trips_without_filing_an_override for why
    that is still safe."""
    box = row(ran["dayOnePolish"], "soft_costs")["inputs"][0]
    assert box["value"] == ""
    assert box["placeholder"] == "16"
    assert row(ran["dayOnePolish"], "soft_costs")["drops"] == [], (
        "a line with no rule filed offered to stop overriding one")


@needs_node
def test_a_typed_dollar_figure_gets_a_dollar_sign_not_a_percent(ran):
    """The other affordance. A bond filed as a flat `750` is DOLLARS, and priceChain reads the
    same number the same way -- a number under 1 in absolute value is a rate, 1 or more is money.

    If the box said 750% while the figure said $750.00, one of the two would be lying, and the
    one people would believe is the box they typed into."""
    r = ran["dollars"]
    assert r["advanced"] is False
    assert parts(r) == {"value": "750"}
    assert "$" in r["rateText"], r["rateText"]
    assert "%" not in r["rateText"].replace("Advanced", ""), r["rateText"]
    assert (r["rate"], r["figure"]) == ("", "$750.00")
    # And it reads a typed separator back, then writes the formula plainly.
    assert ran["dollarsEdited"]["body"]["formula"] == "1250"
    assert ran["dollarsEdited"]["row"]["figure"] == "$1,250.00"


@needs_node
def test_a_markup_wrapped_rate_is_still_one_number(ran):
    """`MARKUP(30%)` is a divide-up of ONE rate. That is a fact about the arithmetic, not about
    how many numbers the answer has, so it gets the one-number box -- and what comes back out
    still says MARKUP, or GP would quietly become a mark-on."""
    r = ran["markupFlat"]
    assert r["advanced"] is False
    assert parts(r) == {"value": "30"}
    # A divide-up on an $85,000 base: ROUNDUP(85000/0.7) - 85000.
    assert r["figure"] == "$36,429.00"
    assert r["rate"] == "", "a divide-up printed a percentage nobody typed"


# ── the ladders ───────────────────────────────────────────────────────
@needs_node
def test_the_banded_lines_are_a_ladder_of_typed_numbers_not_a_formula_string(ran):
    """GP's five bands, as five rows a person can read down.

    The formula this replaces was the single most complicated thing on the page. Every threshold
    and every rate is its own box; the last row has no threshold because it is what everything
    above the top band gets."""
    r = ran["ladder"]["gp"]
    assert r["advanced"] is False
    assert [b["label"] for b in r["bands"]] == ["up to"] * 4 + ["above that"]
    assert [b["values"] for b in r["bands"]] == [
        ["6,500", "52"], ["15,000", "45"], ["22,500", "35"], ["32,500", "32"], ["30"]]
    # Every band but the default can be taken out; the default cannot, or BAND has no answer for
    # a job above the top ceiling.
    assert [b["del"] for b in r["bands"]] == [True, True, True, True, False]


@needs_node
def test_the_hard_bids_local_jobs_rule_is_a_checkbox_on_the_step_it_belongs_to(ran):
    """Kyle's give-back steps UP with job size and the smaller step is local-jobs-only.

    Rendered as thresholds you type and one checkbox, instead of
    `IF(hard_bid_on, IF(subtotal>=60000, -4%, IF(local, IF(subtotal>=13000, -2.5%, 0), 0)), 0)`.
    The terminator is not a box: a give-back that does not apply is nothing off, not a rate of
    nothing."""
    r = ran["ladder"]["hard_bid"]
    assert r["advanced"] is False
    assert [b["label"] for b in r["bands"]] == ["from", "from", "otherwise"]
    assert [b["values"] for b in r["bands"]] == [["60,000", "-4"], ["13,000", "-2.5"], []]
    assert [(c["part"], c["checked"]) for c in r["checks"]] == [
        ("local-0", False), ("local-1", True)]
    assert "nothing off" in r["bandsText"]


@needs_node
def test_ticking_local_jobs_only_moves_that_step_inside_kyles_own_gate(ran):
    """The checkbox writes the shape Kyle's cell has, not a new one.

    Ticking it on the top step means BOTH steps need a local job, and the `IF(local, ...)` gate
    wraps both -- which is exactly what the person asked for by ticking it. It commits on
    `change`, because a checkbox is a decision rather than half a word, and the focus goes
    straight back onto the box that was ticked."""
    body = ran["localTicked"]["body"]
    assert body["formula"] == (
        "IF(hard_bid_on, IF(local, IF(subtotal>=60000, -4%, "
        "IF(subtotal>=13000, -2.5%, 0)), 0), 0)"), body["formula"]
    assert ran["localTicked"]["focused"] == "s-hard_bid-local-0", (
        "the repaint on change stole the focus from the box that was ticked")
    assert [c["checked"] for c in ran["localTicked"]["row"]["checks"]] == [True, True]


@needs_node
def test_every_built_in_ladder_round_trips_without_filing_an_override(ran):
    """LOOKING AT A CONTROL MUST NOT FILE A RATE.

    A one-number box for a line with nothing filed is empty, so leaving it reads back as "nothing
    filed". A ladder cannot do that -- it is seeded from the built-in -- so leaving it reads back
    as the built-in, and the page compares an edit against what the control was RENDERED FROM
    rather than against the stored string. The harness tabs out of all nine of GP's boxes and all
    four of the hard bid's, and then every flat box, touching none of them.

    Mutation: test_a_ladder_with_no_baseline_files_an_override_for_looking_at_it."""
    assert ran["roundTripPuts"] == [], (
        "tabbing across an untouched ladder filed an override: %r" % ran["roundTripPuts"])
    assert ran["roundTripPutsAfterFlat"] == [], (
        "tabbing out of an untouched one-number box filed an override: %r"
        % ran["roundTripPutsAfterFlat"])


@needs_node
def test_tabbing_across_a_ladder_repaints_nothing(ran):
    """The other half of it, and the half that is about the keyboard.

    Nothing changed, so nothing is repainted -- which is what keeps the box the browser is moving
    the focus INTO in existence. The assertion is node identity: the same object before and after
    means the table was not rebuilt underneath it."""
    assert ran["tabNoEdit"]["puts"] == 0
    assert ran["tabNoEdit"]["sameNode"] is True, (
        "leaving an untouched box rebuilt the table under the focus that was moving into it")


@needs_node
def test_typing_a_band_rate_files_the_built_in_with_one_number_changed(ran):
    """The round-trip contract, from the other end: 52 becomes 50 and NOTHING else moves.

    Byte for byte against the built-in string. If the serializer drifted -- a space, a percent
    written as a decimal, the bands reordered -- this is where it shows, because the formula it
    writes is the one a future pricing engine will read."""
    assert ran["bandEdit"]["body"]["formula"] == GP_BANDS.replace("6500,52%", "6500,50%")
    assert ran["bandEdit"]["body"]["line_key"] == "gp"
    assert ran["bandEdit"]["body"]["layout"] == "polish"


@needs_node
def test_the_caret_lands_where_the_keyboard_was_going_not_where_it_was(ran):
    """A repaint on the way out of a box must not throw the caret back out of the row.

    During `focusout` the browser is mid-transition: document.activeElement is still the box being
    LEFT, so "restoring the focus" would yank the caret out of the box the person just tabbed
    into. `ev.relatedTarget` is where it is really going. On a ladder of ten boxes this is the
    difference between typing across a row and being ejected at every field.

    Mutation: test_losing_the_related_target_throws_the_caret_out_of_the_row."""
    assert ran["bandEdit"]["repainted"] is True, (
        "the table was not rebuilt, so this scenario is not testing a repaint at all")
    assert ran["bandEdit"]["focused"] == "s-gp-edge-1", (
        "the caret did not follow the keyboard: %r" % ran["bandEdit"]["focused"])


@needs_node
def test_a_job_size_can_be_typed_the_way_people_type_money(ran):
    """"$16,000" is what somebody types into a box that already reads "15,000".

    Read leniently and written plainly: the formula gets 16000, and the box comes back with the
    separators. A control that refused a dollar sign would be a control people fight."""
    assert ran["commaEdit"]["body"]["formula"] == (
        GP_BANDS.replace("6500,52%", "6500,50%").replace("15000,45%", "16000,45%"))


@needs_node
def test_a_band_can_be_added_and_is_not_saved_half_filled(ran):
    """Seal has a SIXTH GP tier and Gyp has seven, and their edges are not on record anywhere in
    this repo -- so an admin has to be able to add a rung. A new one arrives empty, and an empty
    rung is not a rate: it says which half is missing and posts nothing."""
    added = ran["bandAdded"]
    assert added["puts"] == 0
    assert [b["values"] for b in added["row"]["bands"]][-2:] == [["", ""], ["30"]]
    assert "job size and rate" in added["alert"]
    assert added["focused"] == "s-gp-edge-4", "the new band did not get the next keystroke"

    half = ran["bandHalfFilled"]
    assert half["puts"] == 0, "a band with a threshold and no rate was filed"
    shown = [e for e in half["row"]["errmsg"] if not e["hidden"]]
    assert shown and "needs a rate" in shown[0]["text"], shown
    # AND THE TYPED CHARACTERS SURVIVED. The message is written without a repaint precisely so
    # that half-finished work is not thrown away by the act of complaining about it.
    assert parts(half["row"])["edge-4"] == "45000"


@needs_node
def test_a_new_band_lands_before_the_default_not_after_it(ran):
    """A band is a CEILING and the default is what everything above the top ceiling gets, so a
    rung appended after the default could never be reached. BAND's own first-match-wins order is
    what makes this a correctness question rather than a tidiness one."""
    assert ran["bandFilled"]["body"]["formula"] == (
        "MARKUP(BAND(subtotal, 6500,52%, 15000,45%, 22500,35%, 32500,32%, 45000,31%, 30%))")
    assert [b["values"] for b in ran["bandFilled"]["row"]["bands"]] == [
        ["6,500", "52"], ["15,000", "45"], ["22,500", "35"], ["32,500", "32"],
        ["45,000", "31"], ["30"]]


@needs_node
def test_a_band_can_be_taken_back_out(ran):
    """And taking it out is a decision, not half a word, so it saves at once -- back to exactly
    the built-in string it started from."""
    assert ran["bandRemoved"]["body"]["formula"] == GP_BANDS
    assert [b["values"] for b in ran["bandRemoved"]["row"]["bands"]] == [
        ["6,500", "52"], ["15,000", "45"], ["22,500", "35"], ["32,500", "32"], ["30"]]


# ── Advanced: the expression box is still there ───────────────────────
@needs_node
def test_the_expression_box_is_still_there_behind_advanced(ran):
    """Somebody who has already filed a hand-written expression, or who needs one the ladder
    cannot express, keeps working. The box is the same box; it is one click away instead of being
    the only thing on offer -- and the click puts the caret in it."""
    r = ran["advOpened"]
    assert r["advanced"] is True
    assert r["inputs"][0]["placeholder"] == GP_BANDS, (
        "the expression box does not show what the chain is using: %r" % r["inputs"][0])
    assert ran["advFocused"] == "f-gp"
    assert [b["text"] for b in r["buttons"] if b["text"]] == ["Use the simple editor"]


@needs_node
def test_advanced_hands_the_row_back_to_the_simple_editor(ran):
    """Both directions, or it is a trapdoor. Nine boxes back."""
    assert ran["advClosed"]["advanced"] is False
    assert len(ran["advClosed"]["inputs"]) == 9


@needs_node
def test_advanced_is_not_a_trapdoor_on_a_line_with_nothing_on_record(ran):
    """`escalation` has no filed rule and no built-in, so its simple control is an empty rate box.

    Opening Advanced there and finding no way back would be the same corner the off row was in
    until 2026-09-04: one exit, which disappears the moment it is used. "No simple editor" means
    exactly one thing -- a formula is stored that no box can hold -- and an empty row is not
    that."""
    r = ran["escalationAdvanced"]
    assert r["advanced"] is True, "the Advanced click did nothing, so this proves nothing"
    assert "Use the simple editor" in [b["text"] for b in r["buttons"]], (
        "a blank row opened in Advanced with no way back: %r"
        % [b["text"] for b in r["buttons"]])


@needs_node
def test_a_formula_no_simple_control_can_hold_opens_in_advanced_by_itself(ran):
    """The rule that keeps the simple controls honest.

    `IF(taxable, 16%, 13%)` is a real answer somebody could file and no ladder can hold it, so the
    row opens in Advanced rather than being misrepresented by a box that cannot show it. Same for
    Gyp's soft-costs BUILT-IN, which is a whole expression with Kyle's own `"error"` sentinel in
    it.

    Mutation: test_a_simple_control_for_an_expression_it_cannot_hold_misrepresents_it."""
    forced = ran["forcedAdvanced"]
    assert forced["advanced"] is True
    assert forced["inputs"][0]["value"] == "IF(taxable, 16%, 13%)"
    assert any("no simple editor" in n for n in forced["notes"]), forced["notes"]
    # A row with nowhere to go back TO is not offered a door.
    assert "Use the simple editor" not in [b["text"] for b in forced["buttons"]]

    gyp = ran["gypSoftCosts"]
    assert gyp["advanced"] is True
    assert gyp["inputs"][0]["value"] == "", "nothing is filed, so the box is empty"
    assert gyp["inputs"][0]["placeholder"].startswith('IF(OR(B5="Yes"')
    assert any("whole expression" in n for n in gyp["notes"]), gyp["notes"]


@needs_node
def test_a_row_that_is_only_its_built_in_says_so_and_a_filed_one_does_not(ran):
    """"Not overridden yet" is a fact about the TABLE, not about which control the row got.

    A filed formula the simple editor cannot hold is still an override, and telling somebody their
    own stored rule is the built-in is the kind of wrong that gets typed over."""
    assert any("not overridden yet" in n
               for n in row(ran["dayOnePolish"], "soft_costs")["notes"])
    assert not any("not overridden yet" in n for n in ran["forcedAdvanced"]["notes"]), (
        "a filed rule was reported as the built-in")


# ── the ABSENT state ─────────────────────────────────────────────────
@needs_node
def test_gyps_absent_hard_bid_is_greyed_and_has_nothing_to_type_into(ran):
    """The state the mockup had no design for, and the one mistake this feature exists to prevent.

    Gyp's hard-bid cell is EMPTY in estimate_sheet_5.7.xlsx -- not 0. So the row is present and
    greyed, says which tab it is not used on, and carries NO control: an empty editable box
    invites somebody to fill it in, and there is no correct value to fill in.

    Mutation: read `applies` back off the presence of a formula
    (test_collapsing_applies_into_a_zero_formula_loses_the_absent_state)."""
    r = row(ran["gyp"], "hard_bid")
    assert r["absentClass"] is True, "the absent row is not distinguished from a priced one"
    assert r["inputs"] == [], "an absent line was rendered as an editable box"
    assert r["checks"] == [] and r["bands"] == []
    assert "not used on gypsum underlayment" in r["rateText"].lower()
    assert "not the same as 0%" in r["rateText"]


@needs_node
def test_an_absent_line_shows_no_figure_at_all_not_a_zero(ran):
    """"Does not exist on this tab" has no dollar value, and "0%" reads as a discount declined."""
    r = row(ran["gyp"], "hard_bid")
    assert r["preview"] == "—"
    assert r["figure"] == "—"
    assert "0%" not in r["preview"]
    assert "$" not in r["preview"]
    assert r["run"] == "", "an absent line printed a running total it does not contribute to"
    assert r["appliesText"] == "Not used"


@needs_node
def test_a_filed_zero_still_prices_as_zero_beside_it(ran):
    """The other half of the distinction, on the same screen.

    bond is filed as `'0'` with applies=true on the Gyp scenario -- it exists and prices to
    nothing -- and it reads $0.00 with a live box holding a real 0. If the two rows ever render
    alike, one of the two facts has been lost."""
    absent = row(ran["gyp"], "hard_bid")
    zero = row(ran["gyp"], "bond")
    assert zero["rate"] == "0%" and zero["figure"] == "$0.00"
    assert zero["absentClass"] is False
    assert parts(zero) == {"value": "0"}
    assert zero["appliesText"] == "Yes"
    assert zero["preview"] != absent["preview"]


@needs_node
def test_an_absent_line_filed_by_hand_renders_the_same_way(ran):
    """`applies=false, formula=NULL` in the TABLE, not just as a built-in default.

    rowState reads applies off the column and never re-derives it, so an admin switching Polish's
    hard bid off gets the identical presentation Gyp gets by default."""
    r = row(ran["filedAbsent"], "hard_bid")
    assert r["absentClass"] is True
    assert r["inputs"] == []
    assert r["figure"] == "—"
    assert "not used on polished concrete" in r["rateText"].lower()


# -- the off row's one exit -------------------------------------------------
# The presentation above is deliberate and stays. What was missing is the way OUT of it. An off
# row has no box to type in, so the only control it can carry is the one that hands the line back
# to its built-in -- and until 2026-09-04 it carried nothing. The only route home was the
# transient on-but-unsaved row: flip the switch on, the button appears, blur the empty box, and
# the row reverts to off and takes the button with it. A corner with a single exit that vanished
# when touched, which is the shape of the send-gate loop RJ reported the day before.


@needs_node
def test_a_line_switched_off_keeps_the_one_control_that_undoes_it(ran):
    """Both routes into the off state, because they are different code paths reaching one row.

    `filedAbsent` arrives with `applies=false` already on the row; `switchedOff` gets there by an
    admin flipping the switch on this page. Either way the row HAS a rule id, so there is
    something to stop overriding -- and no control, so nothing else could offer it.

    Mutation: stop calling dropBtnHtml from the ABSENT branch
    (test_an_off_row_with_no_way_back_is_the_corner_this_undoes)."""
    for name, line in (("filedAbsent", "hard_bid"), ("switchedOff", "soft_costs")):
        r = row(ran[name], line)
        assert r["absentClass"] is True, "%s/%s is not the off row this is about" % (name, line)
        assert r["inputs"] == [], (
            "%s/%s grew a box, so the row is no longer the one with no other exit" % (name, line))
        assert r["drops"] == ["Stop overriding this line"], (
            "%s/%s offers no way back to the built-in: %r" % (name, line, r["drops"]))
        assert [b["text"] for b in r["buttons"] if b["text"]] == ["Stop overriding this line"], (
            "%s/%s grew some other control on an off row: %r"
            % (name, line, [b["text"] for b in r["buttons"]]))


@needs_node
def test_a_line_that_was_never_overridden_offers_nothing_to_stop(ran):
    """THE COUNTEREXAMPLE. Gyp's hard bid is absent because Kyle's workbook has no such cell --
    `applies=false` as a built-in DEFAULT, with no filed rule and so no id. "Stop overriding this
    line" there would be a button with nothing to remove, and pressing it could only fail.

    Without this, the test above would pass just as green on a version that painted the button on
    every absent row."""
    r = row(ran["gyp"], "hard_bid")
    assert r["absentClass"] is True
    assert r["buttons"] == [], (
        "a line nobody has overridden offers to stop overriding it: %r"
        % [b["text"] for b in r["buttons"]])


@needs_node
def test_the_way_back_from_an_off_row_actually_removes_the_rule(ran):
    """Clicked for real, through the page's own delegated [data-drop] handler. A button that
    paints and does nothing would be a worse corner than no button -- so the DELETE, the words on
    the confirm, and the state of the row afterwards are all asserted, not the markup alone."""
    d = ran["filedAbsentDrop"]
    assert d["deletes"] == ["/api/markup/rules/polish-hard_bid"], d["deletes"]
    c = d["confirm"] or {}
    assert c.get("name") == "Hard bid discount", c
    # The expensive misreading, said out loud: removing a rule is not "charge nothing here".
    assert "does not price the line at nothing" in c.get("detail", ""), c
    after = row(d["after"], "hard_bid")
    assert after["absentClass"] is False, "the row is still off after its rule was removed"
    assert (after["rate"], after["figure"]) == ("-4%", "-$4,857.16"), (
        "the line did not come back at its built-in rate: %r" % after["preview"])
    assert after["drops"] == [], "there is still an override to stop after the rule is gone"


@needs_node
def test_switching_a_line_off_files_applies_false_with_no_formula(ran):
    """The PUT body is the distinction, or the backend cannot store it.

    `formula: null` rather than `'0'`, and `applies: false` rather than an omitted key.
    `notes` rides along because markup.validate_rule is NOT partial -- the editor states the whole
    row every time, so a save from this page would otherwise clear a note filed elsewhere."""
    body = ran["switchedOffBody"]
    assert body["applies"] is False
    assert body["formula"] is None
    assert body["line_key"] == "soft_costs"
    assert body["layout"] == "polish"
    assert "notes" in body


@needs_node
def test_switching_a_line_back_on_with_an_empty_box_posts_nothing(ran):
    """`applies=true` with no formula is the state markup.py refuses outright.

    Saying so in the page beats collecting a 400, and the row's own control -- whichever kind it
    turned out to be -- gets the focus so the next keystroke lands where it is needed. Exactly one
    PUT happened in that scenario: the switch-OFF."""
    assert ran["switchOnEmpty"]["puts"] == 1
    assert "Type a rate" in ran["switchOnEmpty"]["alert"]
    assert ran["switchOnEmpty"]["focused"] == "s-soft_costs-value"


# ── a broken line reads Unpriceable, never $0.00 ─────────────────────
@needs_node
def test_an_unreadable_formula_makes_its_own_line_unpriceable(ran):
    """A filed formula with an unbalanced paren. It reports the parse error rather than a total --
    and because no simple control can read it, the row opens in Advanced so the person can see
    the formula the message is about."""
    r = row(ran["invalid"], "hard_bid")
    assert r["figure"] == "Unpriceable"
    assert r["advanced"] is True
    shown = [e for e in r["errmsg"] if not e["hidden"]]
    assert shown and "position" in shown[0]["text"], (
        "a filed formula that cannot be read gives no account of itself")


@needs_node
def test_every_line_below_a_broken_one_is_unpriced_and_the_total_refuses(ran):
    """The cascade, and the sentence that names the culprit -- printed WHERE THE FIGURE IS
    MISSING, because it is the one line of explanation on this page that is about right now.

    Mutation: stop cascading (test_not_cascading_lets_a_broken_chain_print_figures)."""
    snap = ran["invalid"]
    below = markup.CHAIN[markup.CHAIN.index("hard_bid") + 1:]
    for line_key in below:
        r = row(snap, line_key)
        assert r["figure"] == "—", (
            "%s priced a figure off a base that could not be computed" % line_key)
        assert r["run"] == "depends on Hard bid discount", r["run"]
    assert snap["grand"]["preview"] == "Unpriceable"
    assert "Hard bid discount" in snap["grand"]["sub"]
    assert snap["broken"]["hidden"] is False
    assert "Hard bid discount can't be priced." == snap["broken"]["line"]
    assert "rather than zero" in snap["broken"]["rest"]


@needs_node
def test_a_broken_chain_never_prints_a_dollar_zero_anywhere(ran):
    """The one figure that must not appear. $0.00 on a markup line is a bid wrong in the
    customer's favour that nobody notices, which is why it reads Unpriceable instead.

    Mutation: print $0.00 for an unpriceable line
    (test_printing_zero_for_a_broken_line_is_caught)."""
    for name in ("invalid", "sentinel"):
        assert "$0.00" not in ran[name]["chainText"], (
            "%s scenario priced a broken line at zero" % name)


@needs_node
def test_kyles_error_sentinel_is_a_refusal_to_price_not_a_zero(ran):
    """A formula that PARSES and evaluates to the string "error".

    Gyp!B75 is Kyle's own refuse-rather-than-guess branch, and a string is not a number. Excel
    would sum a bare FALSE as 0 here; markup-core.js refuses, and the page says Unpriceable."""
    r = row(ran["sentinel"], "soft_costs")
    assert r["figure"] == "Unpriceable"
    assert ran["sentinel"]["grand"]["preview"] == "Unpriceable"
    assert "Soft costs" in ran["sentinel"]["grand"]["sub"]


@needs_node
def test_a_healthy_chain_prices_the_sample_job_off_the_real_engine(ran):
    """The figures are markup-core.js's, not the harness's.

    Polish's built-in chain over an $85,000 sub-total: GP divides up to $36,429.00, the hard bid
    gives back 4%, and the total lands at $153,165.41. If markup-core.js's ROUNDUP, BAND or MARKUP
    drifts, this is where it shows -- the preview and the bid read the same engine."""
    snap = ran["dayOnePolish"]
    assert (row(snap, "gp")["rate"], row(snap, "gp")["figure"]) == ("", "$36,429.00")
    assert (row(snap, "hard_bid")["rate"], row(snap, "hard_bid")["figure"]) == \
        ("-4%", "-$4,857.16")
    assert (row(snap, "super_pto")["rate"], row(snap, "super_pto")["figure"]) == \
        ("2.7%", "$3,214.94")
    assert (row(snap, "soft_costs")["rate"], row(snap, "soft_costs")["figure"]) == \
        ("16%", "$19,565.88")
    assert snap["grand"]["preview"] == "$153,165.41"
    assert snap["broken"]["hidden"] is True


@needs_node
def test_a_divide_up_gp_does_not_print_a_percentage_nobody_typed(ran):
    """GP hands back DOLLARS, and $36,429 on an $85,000 base back-derives to 42.858%.

    Printing that beside a 30% band would put a number nobody typed on the one line whose
    arithmetic already misleads people -- GP is a divide-up, not a mark-on. So the percentage chip
    appears only when the formula returned a rate."""
    assert row(ran["dayOnePolish"], "gp")["rate"] == ""
    assert row(ran["dayOnePolish"], "soft_costs")["rate"] == "16%"


@needs_node
def test_the_running_total_under_each_amount_is_the_next_lines_base(ran):
    """The chain COMPOUNDS, and this is where the page stops asserting that in a paragraph and
    shows it instead. The arrow under each amount is the total THROUGH that line, so the last one
    equals the grand total and every rate line's own figure is its rate times the arrow above it.

    Checked arithmetically off the engine's own numbers rather than transcribed, so a line priced
    off the wrong base fails here."""
    snap = ran["dayOnePolish"]

    def dollars(text):
        return float(text.replace("→", "").replace("$", "").replace(",", "").strip())

    assert dollars(row(snap, "gp")["run"]) == 85000 + dollars(row(snap, "gp")["figure"])
    # super/PTO is 2.7% of everything above it, which is the arrow on the contingency line.
    above = dollars(row(snap, "contingency")["run"])
    assert round(above * 0.027, 2) == dollars(row(snap, "super_pto")["figure"])
    # And the last arrow in the chain is the total.
    assert dollars(row(snap, "bond")["run"]) == dollars(snap["grand"]["preview"])


# ── the two chain lines nobody sets here ──────────────────────────────
@needs_node
def test_contingency_and_remodel_tax_use_markups_own_sentences(ran):
    """VERBATIM from markup._NOT_EDITABLE, not paraphrased to fit the column.

    Both are refused BY NAME by the backend, and the person reading the screen is entitled to the
    same reason the API would give them. Comparing the strings means a reword on either side is a
    failing test rather than two screens explaining the same rule differently."""
    for line_key, sentence in markup._NOT_EDITABLE.items():
        assert row(ran["dayOnePolish"], line_key)["explain"] == sentence


@needs_node
def test_the_two_context_lines_are_marked_as_set_elsewhere(ran):
    """They are not markup rules and they must not look like rows an admin has not got round to.

    Tinted, chipped, no control, and the disclosure is labelled for the question a reader actually
    has about them -- not "what this does" but "why isn't it here"."""
    for line_key in markup._NOT_EDITABLE:
        r = row(ran["dayOnePolish"], line_key)
        assert r["ctxClass"] is True, "%s does not read as context" % line_key
        assert r["chip"] == "Set elsewhere", r["chip"]
        assert r["helpLabel"] == "Why it isn't here", r["helpLabel"]
    # And the rows an admin DOES set are not marked that way.
    for line_key in markup.LINE_KEYS:
        r = row(ran["dayOnePolish"], line_key)
        assert r["ctxClass"] is False, "%s reads as somebody else's to set" % line_key
        assert r["chip"] == ""


@needs_node
def test_the_read_only_lines_have_no_control_at_all(ran):
    """Not a disabled box -- no box. There is nothing to file, so there is nothing to disable.

    They still show what DOES set them, and they still price into the preview, because a chain
    with two lines missing cannot be read as a chain."""
    for line_key in markup._NOT_EDITABLE:
        r = row(ran["dayOnePolish"], line_key)
        assert r["inputs"] == []
        assert r["checks"] == []
        assert r["switches"] == []
        assert r["buttons"] == []
        assert r["appliesText"] == "Always"
    assert row(ran["dayOnePolish"], "contingency")["figure"] == "$2,500.00"
    assert (row(ran["dayOnePolish"], "remodel_tax")["rate"],
            row(ran["dayOnePolish"], "remodel_tax")["figure"]) == ("7.975%", "$11,312.75")


# ── the prose left the grid ───────────────────────────────────────────
@needs_node
def test_no_row_is_left_without_an_explanation(ran):
    """Every rendered line says what it does, including the ones nobody can edit -- it just says
    it in the row's own disclosure now instead of in a column of prose repeated eight times."""
    for r in ran["dayOnePolish"]["rows"]:
        assert r["explain"].strip(), "%s renders with no explanation" % r["line"]
        assert r["label"].strip()
        assert r["sub"].strip(), "%s has no one-line caption" % r["line"]
        assert r["helpLabel"].strip()


@needs_node
def test_the_explanation_starts_closed_and_survives_a_repaint(ran):
    """A disclosure that snapped shut on every save would be worse than the column it replaced.

    Opened, then a save on a DIFFERENT row rebuilds the whole table -- and it is still open."""
    assert ran["helpClosed"] is False, "the disclosure starts open, so the prose never left"
    assert ran["helpOpen"] is True, "a repaint closed the explanation somebody had opened"


@needs_node
def test_the_column_headings_are_the_four_that_are_left(ran):
    """WHAT IT DOES is gone as a column. FORMULA became RATE, because for six of the eight lines
    the answer is one number."""
    assert ran["dayOnePolish"]["head"] == "LineRateAppliesPreview"


def test_the_intro_is_one_sentence_with_the_rest_behind_a_disclosure():
    """The page opened with two dense paragraphs before any control, and "This is too
    complicated" was the verdict on it.

    Both facts in them are real and both survive -- they are just in a disclosure instead of
    standing in front of the table. Asserted on the page source because it is copy, not
    behaviour: one `.hint` paragraph, and the two things that paragraph used to have to carry."""
    html = (FRONTEND / "markup.html").read_text(encoding="utf-8")
    assert html.count('<p class="hint">') == 1, (
        "the intro is back to more than one paragraph of standing prose")
    assert 'class="help how"' in html, "the 'How the chain works' disclosure is gone"
    for fact in ("How the chain works", "sheet layouts", "no Combo",
                 "running total of everything above it"):
        assert fact in html, "the intro lost a fact worth keeping: %r" % fact


# ── a non-admin ──────────────────────────────────────────────────────
@needs_node
def test_a_non_admin_gets_no_editable_control_anywhere(ran):
    """Fail closed. ADMIN starts false and is settled before the first paint, so the page never
    flashes editable and then locks.

    Not a security boundary -- `_require_admin` in main.py is -- but a button that 403s is a lie
    about what somebody may do. The ladder's checkboxes count: `inputCount` is every input in the
    chain, checkbox or not.

    EXCEPT THE SUB-TOTAL WHAT-IF BOX, which every role gets. The gate is about controls that FILE
    something, and that box files nothing -- it moves a preview figure on this screen only, so no
    amount of typing in it can earn the 403 this test exists to keep somebody out of. It is also
    the control that most serves a non-admin: test_a_non_admin_reads_the_same_facts already says
    the point of their read-only view is answering "what would this do", and a job size you cannot
    change answers that for exactly one job size. Asserted present below rather than ignored.

    Mutation: drop the ADMIN gate (test_dropping_the_admin_gate_hands_a_non_admin_a_box)."""
    for name in ("nonAdminPolish", "nonAdminGyp"):
        snap = ran[name]
        assert snap["inputCount"] == 0, "%s rendered an editable box for a non-admin" % name
        assert snap["switchCount"] == 0, "%s rendered a switch for a non-admin" % name
        assert snap["buttonCount"] == 0, "%s rendered a button for a non-admin" % name
        assert snap["subtotalBoxes"] == 1, (
            "%s lost the sub-total what-if box; it writes nothing and is the one control a "
            "read-only viewer is on this page to use" % name)
    assert ran["nonAdminRequests"] == ["GET"], "a non-admin's page wrote to the API"


@needs_node
def test_a_non_admin_reads_the_same_facts(ran):
    """Read-only is not a redaction. The rates, the applies column and the previews are all there;
    only the controls are gone -- and the note above the table says who to ask.

    A LADDER STILL READS AS A LADDER. A non-admin used to get the raw expression string; they now
    get the same rungs an admin gets, without the boxes, because "what would this do" is the
    question they are on this page to answer."""
    assert ran["nonAdminPolish"]["ro"]["hidden"] is False
    assert ran["dayOnePolish"]["ro"]["hidden"] is True
    assert row(ran["nonAdminPolish"], "soft_costs")["rateText"] == "16%"
    assert (row(ran["nonAdminPolish"], "soft_costs")["rate"],
            row(ran["nonAdminPolish"], "soft_costs")["figure"]) == ("16%", "$19,565.88")
    gp = row(ran["nonAdminPolish"], "gp")["bandsText"]
    for rung in ("6,500", "52%", "32,500", "32%", "above that", "30%"):
        assert rung in gp, "a non-admin cannot read GP's bands: %r" % gp
    assert "local jobs only" in row(ran["nonAdminPolish"], "hard_bid")["bandsText"]
    # And the absent row still reads absent, which is the fact a non-admin most needs.
    absent = row(ran["nonAdminGyp"], "hard_bid")
    assert absent["absentClass"] is True
    assert absent["appliesText"] == "Not used"
    assert absent["figure"] == "—"


@needs_node
def test_a_403_locks_the_page_rather_than_pretending_the_save_worked(ran):
    """The backend is the gate, so the page believes it.

    An admin flag that resolved wrongly (a role changed in another tab, a stale token) ends with
    the controls gone and a sentence, not with a box that keeps refusing."""
    snap = ran["forbidden"]
    assert snap["inputCount"] == 0
    assert snap["switchCount"] == 0
    assert snap["ro"]["hidden"] is False
    assert "admin-only" in snap["alert"]
    assert "Nothing was saved" in snap["alert"]


# ── day one, when the table is empty ─────────────────────────────────
@needs_node
def test_an_empty_rules_table_is_the_normal_first_state(ran):
    """Day one every line falls back to its hardcoded constant, and the page says so.

    An empty `rules` array is not an error and must not look like a broken page: the one-number
    boxes carry the constant as a PLACEHOLDER, the ladders are seeded from it, and the note above
    the table explains what changing a number does."""
    snap = ran["dayOnePolish"]
    assert snap["fallback"]["hidden"] is False
    assert "normal first state" in snap["fallback"]["text"]
    assert "built into the estimator" in snap["fallback"]["text"]
    assert snap["grand"]["preview"] == "$153,165.41", "an unconfigured tab still prices"


@needs_node
def test_a_tab_with_something_filed_counts_it(ran):
    assert "2 of 5 lines on Gyp are overridden here" in ran["gyp"]["fallback"]["text"]


# ── typing, blurring, and the keyboard ───────────────────────────────
@needs_node
def test_typing_is_never_scolded_mid_word(ran):
    """Half a rate is always half a rate. Being told so on every keystroke teaches somebody to
    ignore the message, so validation happens on the way OUT of the box."""
    assert ran["midWord"]["puts"] == 0
    assert all(e["hidden"] for e in ran["midWord"]["errmsg"]), (
        "a half-typed rate was marked wrong mid-word")


@needs_node
def test_a_number_box_refuses_what_is_not_a_number_and_keeps_what_was_typed(ran):
    """"sixteen" is not a rate. It is refused on blur, it is not sent, and it is still in the box
    -- the message is written WITHOUT a repaint precisely so that nothing half-finished is thrown
    away by the act of complaining about it."""
    assert ran["badNumberPuts"] == 0, "a non-number was sent to the server"
    r = row(ran["badNumber"], "soft_costs")
    shown = [e for e in r["errmsg"] if not e["hidden"]]
    assert shown and "isn't a number" in shown[0]["text"], shown
    assert r["inputs"][0]["value"] == "sixteen", "the typed text was thrown away"
    assert "finput num err" in r["inputs"][0]["cls"]
    assert "isn't a number" in ran["badNumber"]["alert"]


@needs_node
def test_one_typed_number_files_the_whole_rate(ran):
    """18 in the box becomes `18%` in the table, and the preview follows it."""
    body = ran["goodNumberBody"]
    assert body == {"layout": "polish", "line_key": "soft_costs", "applies": True,
                    "notes": "", "formula": "18%"}
    r = row(ran["goodNumber"], "soft_costs")
    assert (r["rate"], r["figure"]) == ("18%", "$22,011.62"), (
        "the preview did not follow the saved rate: %r" % r["preview"])
    assert r["drops"] == ["Stop overriding this line"]


@needs_node
def test_the_expression_box_still_refuses_what_it_cannot_read(ran):
    """The backend checks a formula's SHAPE and nothing about its grammar, so markup-core.js's
    validate() is what stands between a typo and a stored formula that prices nothing. Reached
    through Advanced now, and unchanged behind it."""
    assert ran["badOnBlurPuts"] == 0, "an unreadable formula was sent to the server"
    r = row(ran["badOnBlur"], "soft_costs")
    shown = [e for e in r["errmsg"] if not e["hidden"]]
    assert shown, "an unreadable formula was accepted silently"
    assert r["inputs"][0]["value"] == "16% *", "the typed text was thrown away"
    assert "finput err" in r["inputs"][0]["cls"]
    assert "can't be read" in ran["badOnBlur"]["alert"]
    # And it does not price -- it takes the rest of the chain down with it rather than reading 0.
    assert r["figure"] == "Unpriceable"
    assert ran["badOnBlur"]["grand"]["preview"] == "Unpriceable"


@needs_node
def test_a_formula_that_reads_is_saved_on_blur_with_the_whole_row(ran):
    body = ran["goodOnBlurBody"]
    assert body == {"layout": "polish", "line_key": "soft_costs", "applies": True,
                    "notes": "", "formula": "18%"}
    r = row(ran["goodOnBlur"], "soft_costs")
    assert (r["rate"], r["figure"]) == ("18%", "$22,011.62")
    assert r["drops"] == ["Stop overriding this line"]


@needs_node
def test_the_switch_is_a_real_button_the_keyboard_can_reach(ran):
    """`<button role="switch" aria-checked>`, never a `<div role="switch" tabindex="0">`.

    A real button gets native tab order, native Space and Enter, and no keydown handler to
    forget. aria-checked is the single source of truth, so there is no separate class to fall out
    of step with it."""
    for r in ran["dayOnePolish"]["rows"]:
        for sw in r["switches"]:
            assert sw["tag"] == "button", "a switch was drawn as a <%s>" % sw["tag"]
            assert sw["type"] == "button", "a switch without type=button submits something"
            assert sw["tabindex"] is None, (
                "a tabindex on a real button is a sign it was copied off a div")
            assert sw["checked"] in ("true", "false")
            assert sw["ariaLabel"], "a switch with no label is unreadable to a screen reader"
    assert ran["dayOnePolish"]["switchCount"] == len(markup.LINE_KEYS)


@needs_node
def test_every_control_in_a_ladder_is_labelled_for_a_screen_reader(ran):
    """Ten identical-looking number boxes in one cell are ten unreadable boxes without this. The
    label says which rung and which half of it."""
    r = ran["ladder"]["gp"]
    labels = [i["ariaLabel"] for i in r["inputs"]]
    assert all(labels), labels
    assert len(set(labels)) == len(labels), "two boxes in one row share a label: %r" % labels
    assert "GP band 1 job size on Polish" in labels
    assert "GP rate above the last band on Polish" in labels
    for c in ran["ladder"]["hard_bid"]["checks"]:
        assert "local jobs only" in c["ariaLabel"], c


@needs_node
def test_the_focus_survives_a_re_render_caret_and_all(ran):
    """A re-render on change that steals the focus somebody just tabbed into is a bug this repo
    has shipped before, so the restore is deliberate rather than hoped for.

    Saving a DIFFERENT row repaints the whole table under the caret twice -- once optimistically,
    once on the response. The box comes back a NEW node both times, and the caret goes back where
    it was."""
    assert ran["focus"]["beforeKey"] == "s-gp-value"
    assert ran["focus"]["afterKey"] == "s-gp-value", "the re-render dropped the focus"
    assert ran["focus"]["sameNode"] is False, (
        "the node was not replaced, so this scenario is not testing a re-render")
    assert ran["focus"]["selection"] == [1, 2], "the caret moved"


# ── stopping an override is not charging nothing ─────────────────────
@needs_node
def test_stopping_an_override_is_worded_as_what_it_does(ran):
    """A soft delete means "stop overriding this line, fall back to the hardcoded constant."

    "Delete" reads as "charge nothing for this line", and that reading is the expensive one -- so
    the confirm says the opposite out loud and names the constant the chain goes back to."""
    c = ran["drop"]["confirm"]
    assert c["title"] == "Stop overriding this line?"
    assert c["confirmText"] == "Stop overriding"
    assert "does not price the line at nothing" in c["detail"]
    assert "16%" in c["detail"], "the confirm did not say what the line falls back to"
    assert "constant built into the estimator" in c["after"]
    assert "delete" not in (c["title"] + c["detail"] + c["confirmText"]).lower()


@needs_node
def test_stopping_an_override_hands_the_line_back_to_its_constant(ran):
    assert ran["drop"]["deletes"] == ["/api/markup/rules/polish-soft_costs"]
    r = row(ran["drop"]["after"], "soft_costs")
    assert r["inputs"][0]["value"] == "", "the removed rule is still in the box"
    assert r["inputs"][0]["placeholder"] == "16"
    assert (r["rate"], r["figure"]) == ("16%", "$19,565.88"), (
        "the line stopped pricing instead of falling back")
    assert r["drops"] == [], "the line still offers to stop overriding a rule that is gone"


@needs_node
def test_declining_the_confirm_removes_nothing(ran):
    assert ran["dropCancelled"]["deletes"] == 0


@needs_node
def test_a_rule_already_removed_in_another_tab_reloads_instead_of_insisting(ran):
    """A 404 means somebody else got there first, and markup.py 404s rather than returning a
    cheerful 200. Re-reading beats arguing with a stale row."""
    assert "already been removed" in ran["dropGone"]["alert"]
    assert ran["dropGone"]["gets"] == 2, "the page kept showing a rule the server no longer has"


# ── the states nobody designs until they happen ──────────────────────
@needs_node
def test_a_failed_load_is_a_designed_state_with_a_way_out(ran):
    """Not an empty table. Every list on this page needs an empty state and an error state
    designed rather than defaulted, and this is the error one."""
    assert "didn't load" in ran["loadFailed"]["stateText"]
    assert "HTTP 500" in ran["loadFailed"]["stateText"]
    assert ran["loadFailed"]["retry"] is True
    assert ran["loadFailed"]["rows"] == [], "a failed load rendered rows anyway"
    assert ran["loadFailedRetryGets"] == 2, "Try again did not try again"


# ── the mutations: each guard above, proved able to fail ─────────────
@needs_node
def test_collapsing_applies_into_a_zero_formula_loses_the_absent_state(tmp_path):
    """THE mistake this feature is shaped to prevent, committed on purpose.

    Re-derive `applies` from anything other than the column and Gyp's empty hard-bid cell becomes
    an editable box on a row that reads as a live line. Proves
    test_gyps_absent_hard_bid_is_greyed_and_has_nothing_to_type_into is not vacuous."""
    mutant = mutate(tmp_path,
                    "      st.applies = rule.applies !== false;",
                    "      st.applies = true;")
    r = row(mutant["filedAbsent"], "hard_bid")
    assert r["absentClass"] is False and r["inputs"], (
        "the mutation changed nothing, so the absent-state assertions prove nothing")


@needs_node
def test_printing_zero_for_a_broken_line_is_caught(tmp_path):
    """Proves test_a_broken_chain_never_prints_a_dollar_zero_anywhere is not vacuous."""
    mutant = mutate(tmp_path,
                    '      return \'<span class="unpriced">Unpriceable</span>\';',
                    '      return \'<span class="amt">$0.00</span>\';')
    assert "$0.00" in mutant["invalid"]["chainText"], "the mutation changed nothing"
    assert row(mutant["invalid"], "hard_bid")["figure"] == "$0.00"


@needs_node
def test_not_cascading_lets_a_broken_chain_print_figures(tmp_path):
    """Proves test_every_line_below_a_broken_one_is_unpriced_and_the_total_refuses is not vacuous.

    Without the cascade, every line under the broken one prices off a base that was never
    computed -- and looks perfectly healthy doing it."""
    mutant = mutate(
        tmp_path,
        '      if (broken) { out[k] = { state: "downstream", dependsOn: broken }; continue; }',
        '      if (false) { out[k] = { state: "downstream", dependsOn: broken }; continue; }')
    assert row(mutant["invalid"], "soft_costs")["figure"] != "—", (
        "the mutation changed nothing")
    assert "$" in row(mutant["invalid"], "soft_costs")["figure"]


@needs_node
def test_dropping_the_admin_gate_hands_a_non_admin_a_box(tmp_path):
    """Proves test_a_non_admin_gets_no_editable_control_anywhere is not vacuous.

    The anchor appears twice -- the rate cell and the applies cell -- and both are mutated,
    because a page that hides the box but keeps the switch is still handing out a 403."""
    mutant = mutate(tmp_path, "    if (!ADMIN) {", "    if (false) {", expect_count=2)
    assert mutant["nonAdminPolish"]["inputCount"] > 0, "the mutation changed nothing"
    assert mutant["nonAdminPolish"]["switchCount"] > 0


@needs_node
def test_an_off_row_with_no_way_back_is_the_corner_this_undoes(tmp_path):
    """Proves test_a_line_switched_off_keeps_the_one_control_that_undoes_it is not vacuous.

    This mutation is not hypothetical -- it is the code as it shipped until 2026-09-04, so what
    the mutant does IS the bug being fixed. Restore it and the off row goes back to having no
    control of any kind, while the row's own rule still sits in the table."""
    absent_tail = '(r.dirty ? " Unsaved." : "") + "</span></span>"'
    mutant = mutate(tmp_path,
                    absent_tail + " +" + chr(10) + "        btnsHtml(dropBtnHtml(r));",
                    absent_tail + ";")
    for name, line in (("filedAbsent", "hard_bid"), ("switchedOff", "soft_costs")):
        r = row(mutant[name], line)
        assert r["buttons"] == [], "the mutation changed nothing for %s/%s" % (name, line)
        assert r["inputs"] == [], (
            "%s/%s has some other exit, so the assertion was never about the button" % (name, line))


@needs_node
def test_dropping_the_admin_half_of_the_gate_hands_a_non_admin_a_delete_button(tmp_path):
    """Proves the ADMIN half of dropBtnHtml's one gate is load-bearing, and it is: the first
    version of this fix gated only on `r.id` and handed a non-admin a delete button, because the
    ABSENT branch returns above the `if (!ADMIN)` fork and never reaches it. One function, one
    rule -- and a mutation to prove the rule is doing work.

    `nonAdminRequests` is included so a page that renders the button is not excused by the server
    refusing the DELETE. A button that 403s is a lie about what somebody may do."""
    mutant = mutate(tmp_path, "if (!ADMIN || !r.id) return \"\";", "if (!r.id) return \"\";")
    hit = [name for name in ("nonAdminPolish", "nonAdminGyp")
           if mutant[name]["buttonCount"] > 0]
    assert hit, "the mutation changed nothing -- the gate may already be somewhere else"
    assert mutant["nonAdminPolish"]["inputCount"] == 0, (
        "the mutant also grew boxes, so this proves nothing about the drop button specifically")


@needs_node
def test_a_dropped_combo_filter_puts_a_combo_tab_on_screen(tmp_path):
    """Proves test_a_combo_tab_cannot_appear_even_if_the_api_sends_one is not vacuous."""
    mutant = mutate(tmp_path,
                    '        return l && String(l).toLowerCase() !== "combo";',
                    "        return !!l;")
    assert "combo" in [t["layout"] for t in mutant["poisoned"]["tabs"]], (
        "the mutation changed nothing")


@needs_node
def test_rewording_a_read_only_sentence_is_caught(tmp_path):
    """Proves test_contingency_and_remodel_tax_use_markups_own_sentences is not vacuous.

    The anchor is a single line of the string concatenation, so the mutation cannot straddle a
    newline and silently no-op -- which is the failure mode that makes a mutation test look green
    while defending nothing."""
    mutant = mutate(tmp_path,
                    '      "not a tab-wide formula. There\'s nothing to file here.",',
                    '      "ask Hanz.",')
    assert row(mutant["dayOnePolish"], "contingency")["explain"] != \
        markup._NOT_EDITABLE["contingency"], "the mutation changed nothing"


@needs_node
def test_a_ladder_with_no_baseline_files_an_override_for_looking_at_it(tmp_path):
    """Proves test_every_built_in_ladder_round_trips_without_filing_an_override is not vacuous.

    The baseline is what the control was RENDERED FROM. Take it away from the seeded ladders and
    every rung recomposes to something that differs from "nothing filed", so simply tabbing across
    GP's five bands files an override nobody chose -- on every tab, for every line, the first time
    anybody puts a cursor near it."""
    mutant = mutate(
        tmp_path,
        '      : (st.simpleFiled || srcModel.kind !== "flat") ? simpleTo(srcModel)',
        '      : (st.simpleFiled || srcModel.kind !== "flat") ? ""')
    assert mutant["roundTripPuts"], "the mutation changed nothing"
    assert mutant["roundTripPuts"][0]["formula"] == GP_BANDS, (
        "the mutant filed something other than the built-in it was seeded with: %r"
        % mutant["roundTripPuts"][0])


@needs_node
def test_losing_the_related_target_throws_the_caret_out_of_the_row(tmp_path):
    """Proves test_the_caret_lands_where_the_keyboard_was_going_not_where_it_was is not vacuous.

    Take `ev.relatedTarget` away and the repaint has nowhere to put the caret, so the person who
    typed 50 into GP's first band and pressed Tab lands nowhere at all -- which on a ten-box cell
    means retrieving the mouse for every single number."""
    mutant = mutate(
        tmp_path,
        '    var goingTo = (rel && rel.getAttribute) ? rel.getAttribute("data-focus") : null;',
        "    var goingTo = null;")
    assert mutant["bandEdit"]["focused"] != "s-gp-edge-1", "the mutation changed nothing"
    assert mutant["bandEdit"]["body"]["formula"] == GP_BANDS.replace("6500,52%", "6500,50%"), (
        "the mutant also stopped saving, so this proves nothing about the focus specifically")


@needs_node
def test_a_simple_control_for_an_expression_it_cannot_hold_misrepresents_it(tmp_path):
    """Proves test_a_formula_no_simple_control_can_hold_opens_in_advanced_by_itself is not vacuous.

    Let simpleFrom answer "one number" for anything it could not read, and a filed
    `IF(taxable, 16%, 13%)` renders as an empty rate box on a row that looks perfectly ordinary --
    the stored formula invisible, and one keystroke away from being replaced by a flat rate."""
    mutant = mutate(
        tmp_path,
        "    return flatFrom(ast) || bandsFrom(ast) || ladderFrom(ast);",
        '    return flatFrom(ast) || bandsFrom(ast) || ladderFrom(ast) || blankFlat("x");')
    r = mutant["forcedAdvanced"]
    assert r["advanced"] is False, "the mutation changed nothing"
    assert "IF(taxable" not in r["rateText"], (
        "the mutant still shows the stored formula, so nothing was misrepresented")


@needs_node
def test_a_typoed_element_id_stops_the_page_dead_here(tmp_path):
    """The reason this file executes the renderer instead of reading it.

    `$("mk-brokn")` is a live-page bug every source assertion in the world would call green: the
    note simply never appears, the page looks fine, and the broken-formula banner silently stops
    warning anybody. Same shape as the ReferenceError that took the CRM board down on 2026-08-12
    with a green suite.

    The harness answers only to ids markup.html actually declares, so a renderer reaching for one
    it does not throws here. Proves that guard is not vacuous -- and that this whole approach
    catches the class of bug it claims to."""
    dest = copy_page(tmp_path, '$("mk-broken")', '$("mk-brokn")')
    proc = subprocess.run(["node", str(HARNESS), str(dest)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode != 0, "a typoed element id ran clean, so the id guard proves nothing"
    assert "mk-brokn" in proc.stderr
    assert "markup.html does not declare" in proc.stderr


# -- what a filed rate actually does today ----------------------------------
# The page shipped claiming, in the present tense, that these rows "override the constants
# hardcoded in the Polish beta's pricing engine". Nothing has ever read them. The test below is
# deliberately two-directional so it retires itself: it fails today if the note goes missing, and
# it fails the day the chain is wired if the note is still there.


def test_the_page_only_claims_a_filed_rate_prices_nothing_while_that_is_true():
    """The words on the screen and the state of the code, asserted against each other.

    A one-directional copy pin would be worse than nothing here. It would hold this sentence in
    place through the very change that makes it false, and the page would go back to lying --
    just in the other direction, and with a green suite vouching for it.

    "Wired" is read off two concrete signals rather than a comment: some page other than the admin
    page loading the expression engine, or some script other than the admin page's fetching the
    rules. Either one means a filed rate can reach a price, and the moment either appears this
    test tells whoever did it to delete the sentence."""
    # Whitespace-normalised, so the sentence being re-wrapped by an editor is not read as the
    # sentence being deleted -- which is exactly how this pin first went red.
    html = " ".join((FRONTEND / "markup.html").read_text(encoding="utf-8").split())
    note = "Filed rates are not pricing anything yet" in html

    engine_pages = {f.name for f in FRONTEND.glob("*.html")
                    if "markup-core.js" in f.read_text(encoding="utf-8")} - {"markup.html"}
    fetchers = {f.name for f in FRONTEND.glob("js/*.js")
                if "api/markup" in f.read_text(encoding="utf-8")} - {"markup.js"}
    wired = engine_pages | fetchers

    if wired:
        assert not note, (
            "the chain is wired up now (%s), so the page's 'not pricing anything yet' sentence "
            "is false -- delete it, and this test with it" % ", ".join(sorted(wired)))
    else:
        assert note, (
            "nothing consumes these rules -- markup-core.js is loaded by markup.html alone and "
            "polish-bid-core.js still owns its own RATES -- so an admin can edit a rate, watch it "
            "save, and move no price at all. The page has to say so.")


def test_the_badge_does_not_promise_an_override_that_does_not_happen():
    """The specific false sentence, kept out by name.

    Narrower than the test above on purpose: the tooltip is the one place that made a positive
    claim about what an edit DOES, and it is the sentence an admin reads just before deciding
    this page is safe to use."""
    html = (FRONTEND / "markup.html").read_text(encoding="utf-8")
    assert "rows override the constants" not in html, (
        "the Beta test badge is promising an override no code performs")
