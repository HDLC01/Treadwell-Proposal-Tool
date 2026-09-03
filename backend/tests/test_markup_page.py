"""The Markup page (frontend/markup.html + js/markup.js), executed out of the real renderer.

EXECUTED, NOT GREPPED. Every assertion below reads nodes that markup.js actually built, via
backend/tests/js/markup-page-harness.js. That is not a style preference: on 2026-08-12 the CRM
board went down on production with `ReferenceError: STAGE_CREATED is not defined` while the whole
suite was green, because every test read the renderer's source text and none of them ran it. A
source assertion also cannot tell a mention of ADMIN from a gate on it.

WHAT THIS PAGE MUST NOT DO -- the four properties worth the harness:

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

The preview figures come from the REAL markup-core.js, so nothing here can pass against a stub
that disagrees with what prices a bid.

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
    """Editable == has a switch and a box. Read off the rendered rows, not off a list.

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
    built-in on this page, so it reads Unpriceable rather than guessing a rate."""
    assert ran["poisoned"]["rowOrder"][-1] == "escalation"
    assert row(ran["poisoned"], "escalation")["preview"] == "Unpriceable"


# ── the ABSENT state ─────────────────────────────────────────────────
@needs_node
def test_gyps_absent_hard_bid_is_greyed_and_has_nothing_to_type_into(ran):
    """The state the mockup had no design for, and the one mistake this feature exists to prevent.

    Gyp's hard-bid cell is EMPTY in estimate_sheet_5.7.xlsx -- not 0. So the row is present and
    greyed, says which tab it is not used on, and carries NO input: an empty editable box invites
    somebody to fill it in, and there is no correct value to fill in.

    Mutation: read `applies` back off the presence of a formula
    (test_collapsing_applies_into_a_zero_formula_loses_the_absent_state)."""
    r = row(ran["gyp"], "hard_bid")
    assert r["absentClass"] is True, "the absent row is not distinguished from a priced one"
    assert r["inputs"] == [], "an absent line was rendered as an editable box"
    assert "not used on gypsum underlayment" in r["formulaText"].lower()
    assert "not the same as 0%" in r["formulaText"]


@needs_node
def test_an_absent_line_shows_no_figure_at_all_not_a_zero(ran):
    """"Does not exist on this tab" has no dollar value, and "0%" reads as a discount declined."""
    r = row(ran["gyp"], "hard_bid")
    assert r["preview"] == "—"
    assert "0%" not in r["preview"]
    assert "$" not in r["preview"]
    assert r["previewClasses"] == ["nodash"]
    assert r["appliesText"] == "Not used"


@needs_node
def test_a_filed_zero_still_prices_as_zero_beside_it(ran):
    """The other half of the distinction, on the same screen.

    bond is filed as `'0'` with applies=true on the Gyp scenario -- it exists and prices to
    nothing -- and it reads $0.00 with a live box. If the two rows ever render alike, one of the
    two facts has been lost."""
    absent = row(ran["gyp"], "hard_bid")
    zero = row(ran["gyp"], "bond")
    assert zero["preview"] == "0%$0.00"
    assert zero["absentClass"] is False
    assert zero["inputs"] and zero["inputs"][0]["value"] == "0"
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
    assert r["preview"] == "—"
    assert "not used on polished concrete" in r["formulaText"].lower()


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

    Saying so in the page beats collecting a 400, and the box gets the focus so the next keystroke
    lands where it is needed. Exactly one PUT happened in that scenario -- the switch-OFF."""
    assert ran["switchOnEmpty"]["puts"] == 1
    assert "Type a formula" in ran["switchOnEmpty"]["alert"]
    assert ran["switchOnEmpty"]["focused"] == "f-soft_costs"


# ── a broken line reads Unpriceable, never $0.00 ─────────────────────
@needs_node
def test_an_unreadable_formula_makes_its_own_line_unpriceable(ran):
    """A filed formula with an unbalanced paren. It reports the parse error rather than a total."""
    r = row(ran["invalid"], "hard_bid")
    assert r["preview"] == "Unpriceable"
    assert r["previewClasses"] == ["unpriced"]
    shown = [e for e in r["errmsg"] if not e["hidden"]]
    assert shown and "position" in shown[0]["text"], (
        "a filed formula that cannot be read gives no account of itself")


@needs_node
def test_every_line_below_a_broken_one_is_unpriced_and_the_total_refuses(ran):
    """The cascade, and the sentence that names the culprit.

    Mutation: stop cascading (test_not_cascading_lets_a_broken_chain_print_figures)."""
    snap = ran["invalid"]
    below = markup.CHAIN[markup.CHAIN.index("hard_bid") + 1:]
    for line_key in below:
        assert row(snap, line_key)["preview"] == "—", (
            "%s priced a figure off a base that could not be computed" % line_key)
    assert snap["grand"]["preview"] == "Unpriceable"
    assert "Hard bid discount" in snap["grand"]["explain"]
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
    assert r["preview"] == "Unpriceable"
    assert ran["sentinel"]["grand"]["preview"] == "Unpriceable"
    assert "Soft costs" in ran["sentinel"]["grand"]["explain"]


@needs_node
def test_a_healthy_chain_prices_the_sample_job_off_the_real_engine(ran):
    """The figures are markup-core.js's, not the harness's.

    Polish's built-in chain over an $85,000 sub-total: GP divides up to $36,429.00, the hard bid
    gives back 4%, and the total lands at $153,165.41. If markup-core.js's ROUNDUP, BAND or MARKUP
    drifts, this is where it shows -- the preview and the bid read the same engine."""
    snap = ran["dayOnePolish"]
    assert row(snap, "gp")["preview"] == "$36,429.00"
    assert row(snap, "hard_bid")["preview"] == "-4%-$4,857.16"
    assert row(snap, "super_pto")["preview"] == "2.7%$3,214.94"
    assert row(snap, "soft_costs")["preview"] == "16%$19,565.88"
    assert snap["grand"]["preview"] == "$153,165.41"
    assert snap["broken"]["hidden"] is True


@needs_node
def test_a_divide_up_gp_does_not_print_a_percentage_nobody_typed(ran):
    """GP hands back DOLLARS, and $36,429 on an $85,000 base back-derives to 42.858%.

    Printing that beside a 30% band would put a number nobody typed on the one line whose
    arithmetic already misleads people -- GP is a divide-up, not a mark-on. So the percentage chip
    appears only when the formula returned a rate."""
    assert row(ran["dayOnePolish"], "gp")["previewClasses"] == ["amt"]
    assert row(ran["dayOnePolish"], "soft_costs")["previewClasses"] == ["pct", "amt"]


# ── the two read-only chain lines ────────────────────────────────────
@needs_node
def test_contingency_and_remodel_tax_use_markups_own_sentences(ran):
    """VERBATIM from markup._NOT_EDITABLE, not paraphrased to fit the column.

    Both are refused BY NAME by the backend, and the person reading the screen is entitled to the
    same reason the API would give them. Comparing the strings means a reword on either side is a
    failing test rather than two screens explaining the same rule differently."""
    for line_key, sentence in markup._NOT_EDITABLE.items():
        assert row(ran["dayOnePolish"], line_key)["explain"] == sentence


@needs_node
def test_the_read_only_lines_have_no_control_at_all(ran):
    """Not a disabled box -- no box. There is nothing to file, so there is nothing to disable.

    They still show what DOES set them, and they still price into the preview, because a chain
    with two lines missing cannot be read as a chain."""
    for line_key in markup._NOT_EDITABLE:
        r = row(ran["dayOnePolish"], line_key)
        assert r["inputs"] == []
        assert r["switches"] == []
        assert r["buttons"] == []
        assert r["appliesText"] == "Always"
    assert row(ran["dayOnePolish"], "contingency")["preview"] == "$2,500.00"
    assert row(ran["dayOnePolish"], "remodel_tax")["preview"] == "7.975%$11,312.75"


# ── a non-admin ──────────────────────────────────────────────────────
@needs_node
def test_a_non_admin_gets_no_editable_control_anywhere(ran):
    """Fail closed. ADMIN starts false and is settled before the first paint, so the page never
    flashes editable and then locks.

    Not a security boundary -- `_require_admin` in main.py is -- but a button that 403s is a lie
    about what somebody may do.

    Mutation: drop the ADMIN gate (test_dropping_the_admin_gate_hands_a_non_admin_a_box)."""
    for name in ("nonAdminPolish", "nonAdminGyp"):
        snap = ran[name]
        assert snap["inputCount"] == 0, "%s rendered an editable box for a non-admin" % name
        assert snap["switchCount"] == 0, "%s rendered a switch for a non-admin" % name
        assert snap["buttonCount"] == 0, "%s rendered a button for a non-admin" % name
    assert ran["nonAdminRequests"] == ["GET"], "a non-admin's page wrote to the API"


@needs_node
def test_a_non_admin_reads_the_same_facts(ran):
    """Read-only is not a redaction. The formulas, the applies column and the previews are all
    there; only the controls are gone -- and the note above the table says who to ask."""
    assert ran["nonAdminPolish"]["ro"]["hidden"] is False
    assert ran["dayOnePolish"]["ro"]["hidden"] is True
    assert row(ran["nonAdminPolish"], "soft_costs")["formulaText"].startswith("16%")
    assert row(ran["nonAdminPolish"], "soft_costs")["preview"] == "16%$19,565.88"
    # And the absent row still reads absent, which is the fact a non-admin most needs.
    absent = row(ran["nonAdminGyp"], "hard_bid")
    assert absent["absentClass"] is True
    assert absent["appliesText"] == "Not used"
    assert absent["preview"] == "—"


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

    An empty `rules` array is not an error and must not look like a broken page: the boxes carry
    the constant as a PLACEHOLDER, and the note above the table explains what typing does."""
    snap = ran["dayOnePolish"]
    assert snap["fallback"]["hidden"] is False
    assert "normal first state" in snap["fallback"]["text"]
    assert "built into the estimator" in snap["fallback"]["text"]
    assert snap["grand"]["preview"] == "$153,165.41", "an unconfigured tab still prices"


@needs_node
def test_the_box_is_empty_and_the_constant_is_only_a_placeholder(ran):
    """Prefilling the box with a value that is not stored would be a lie about state, and the
    first blur would save it as though somebody had chosen it."""
    box = row(ran["dayOnePolish"], "soft_costs")["inputs"][0]
    assert box["value"] == ""
    assert box["placeholder"] == "16%"
    assert row(ran["dayOnePolish"], "soft_costs")["buttons"] == [], (
        "a line with no rule filed offered to stop overriding one")


@needs_node
def test_a_tab_with_something_filed_counts_it(ran):
    assert "2 of 5 lines on Gyp are overridden here" in ran["gyp"]["fallback"]["text"]


# ── typing, blurring, and the keyboard ───────────────────────────────
@needs_node
def test_typing_is_never_scolded_mid_word(ran):
    """Half a formula is always invalid. Being told so on every keystroke teaches somebody to
    ignore the message, so validation happens on the way OUT of the box."""
    assert ran["midWord"]["puts"] == 0
    assert all(e["hidden"] for e in ran["midWord"]["errmsg"]), (
        "a half-typed formula was marked wrong mid-word")


@needs_node
def test_a_formula_that_cannot_be_read_is_refused_on_blur_and_not_sent(ran):
    """The backend checks a formula's SHAPE and nothing about its grammar, so markup-core.js's
    validate() is what stands between a typo and a stored formula that prices nothing."""
    assert ran["badOnBlurPuts"] == 0, "an unreadable formula was sent to the server"
    r = row(ran["badOnBlur"], "soft_costs")
    shown = [e for e in r["errmsg"] if not e["hidden"]]
    assert shown, "an unreadable formula was accepted silently"
    assert r["inputs"][0]["value"] == "16% *", "the typed text was thrown away"
    assert "finput err" in r["inputs"][0]["cls"]
    assert "can't be read" in ran["badOnBlur"]["alert"]
    # And it does not price -- it takes the rest of the chain down with it rather than reading 0.
    assert r["preview"] == "Unpriceable"
    assert ran["badOnBlur"]["grand"]["preview"] == "Unpriceable"


@needs_node
def test_a_formula_that_reads_is_saved_on_blur_with_the_whole_row(ran):
    body = ran["goodOnBlurBody"]
    assert body == {"layout": "polish", "line_key": "soft_costs", "applies": True,
                    "notes": "", "formula": "18%"}
    r = row(ran["goodOnBlur"], "soft_costs")
    assert r["preview"] == "18%$22,011.62", "the preview did not follow the saved formula"
    assert [b["text"] for b in r["buttons"]] == ["Stop overriding this line"]


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
def test_the_focus_survives_a_re_render_caret_and_all(ran):
    """A re-render on change that steals the focus somebody just tabbed into is a bug this repo
    has shipped before, so the restore is deliberate rather than hoped for.

    Saving a DIFFERENT row repaints the whole table under the caret twice -- once optimistically,
    once on the response. The box comes back a NEW node both times, and the caret goes back where
    it was."""
    assert ran["focus"]["beforeKey"] == "f-gp"
    assert ran["focus"]["afterKey"] == "f-gp", "the re-render dropped the focus"
    assert ran["focus"]["sameNode"] is False, (
        "the node was not replaced, so this scenario is not testing a re-render")
    assert ran["focus"]["selection"] == [3, 5], "the caret moved"


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
    assert r["inputs"][0]["placeholder"] == "16%"
    assert r["preview"] == "16%$19,565.88", "the line stopped pricing instead of falling back"
    assert r["buttons"] == [], "the line still offers to stop overriding a rule that is gone"


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


@needs_node
def test_no_row_is_left_without_an_explanation(ran):
    """Every rendered line says what it does, including the ones nobody can edit."""
    for r in ran["dayOnePolish"]["rows"]:
        assert r["explain"].strip(), "%s renders with no explanation" % r["line"]
        assert r["label"].strip()


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
    assert row(mutant["invalid"], "hard_bid")["preview"] == "$0.00"


@needs_node
def test_not_cascading_lets_a_broken_chain_print_figures(tmp_path):
    """Proves test_every_line_below_a_broken_one_is_unpriced_and_the_total_refuses is not vacuous.

    Without the cascade, every line under the broken one prices off a base that was never
    computed -- and looks perfectly healthy doing it."""
    mutant = mutate(
        tmp_path,
        '      if (broken) { out[k] = { state: "downstream", dependsOn: broken }; continue; }',
        '      if (false) { out[k] = { state: "downstream", dependsOn: broken }; continue; }')
    assert row(mutant["invalid"], "soft_costs")["preview"] != "—", (
        "the mutation changed nothing")
    assert "$" in row(mutant["invalid"], "soft_costs")["preview"]


@needs_node
def test_dropping_the_admin_gate_hands_a_non_admin_a_box(tmp_path):
    """Proves test_a_non_admin_gets_no_editable_control_anywhere is not vacuous.

    The anchor appears twice -- the formula cell and the applies cell -- and both are mutated,
    because a page that hides the box but keeps the switch is still handing out a 403."""
    mutant = mutate(tmp_path, "    if (!ADMIN) {", "    if (false) {", expect_count=2)
    assert mutant["nonAdminPolish"]["inputCount"] > 0, "the mutation changed nothing"
    assert mutant["nonAdminPolish"]["switchCount"] > 0


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
