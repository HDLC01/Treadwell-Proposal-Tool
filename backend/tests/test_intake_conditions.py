"""The job-condition toggles on the live intake form.

Hanz, 2026-09-02: *"For the polish beta we want to use the existing intake form v1 (not the beta).
The v2 is just add it with the toggle buttons."*

So the beta's five switches moved onto `frontend/index.html` and grew to ten: the original five
flags, plus **renovation**, **dye**, **joint filler**, **removal of existing joint filler** and the
**epoxy bulk material discount**. Every one of the five new ones is a cell that already exists in
Kyle's workbook, already backed by a dropdown, and already moving real money -- none of them had a
control on any form until now, and `Epoxy!B10` was set only by the AI autofill prompt.

EXECUTED, NOT GREPPED, and for this feature that is not a style preference:

  * **The literals are the feature.** `Epoxy!D41` is read by six formulas shaped
    `IF($D$41=$V$136,...)`. Kyle's `V136`/`V137` hold ``BULK Discount ON`` and
    ``Bulk Discount OFF`` -- mixed case, and inconsistent with each other. Any other casing takes
    the OFF branch in total silence: no error, no warning, just a bid without the discount in it.
    A test that compares the toggle against a string typed into this file would agree with a typo.
    So the comparisons below are read **out of the workbook**, live.
  * **"Off" must be a word, not an absence.** `Polish!C17` is ``IF(B10="New",0.05,0.15)``, so a
    blank `B10` takes the **Reno** branch and triples the patch material rate. Only running the
    writer can tell you whether "off" writes ``"New"`` or writes nothing at all.
  * **A toggle is a DOM effect.** The switches are built by string concatenation at runtime, so no
    source read can confirm one got a track, an `aria-checked`, or a `data-cond` its own listener
    can find. Per [[execute-the-renderer-not-its-source]].
  * **Space and Enter are a listener that exists or does not.** The beta's switches carried
    ``role="switch" tabindex="0"`` and a comment about keyboard reachability, and `wire()` bound a
    delegated click and nothing else -- so they announced themselves to a screen reader as
    switches and then ignored the two keys that operate one. That is the shape of bug a source
    read cannot see and [[browser-walks-find-keyboard-bugs]] was written about.

`tests/js/beta-routing-harness.js` runs the real `js/index.js` top to bottom against a DOM stub,
flips the real work-type radios, clicks and keys the real rendered switches, and reports the
`cell_values` map that actually came out. See its header for the rest.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "beta-routing-harness.js"
TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "templates" / "estimate_sheet_5.7.xlsx"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def cond():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed -- read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])["conditions"]


@pytest.fixture(scope="module")
def sheet():
    """Kyle's workbook, so the assertions below are anchored to it and not to this file."""
    openpyxl = pytest.importorskip("openpyxl")
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        wb = openpyxl.load_workbook(TEMPLATE)
    return wb


# ── the shape Hanz asked for by name ────────────────────────────────────────
@needs_node
def test_every_condition_renders_as_a_toggle(cond):
    """Toggles, not checkboxes.

    The same thing `test_all_five_conditions_render_as_toggles` pins on the beta page, with the
    same reason: he asked for toggle buttons by name. A checkbox rewrite is tempting because
    `TW.readForm` round-trips `type="checkbox"` for free -- this is what stops it.
    """
    s = cond["shape"]
    assert s["role"] == "switch"
    assert s["hasTrack"] and s["allHaveTrack"], "a switch with no track is a checkbox"
    assert s["allHaveRole"], "every one announces itself as a switch"
    assert s["allFocusable"] and s["tabindex"] == "0", "and every one is reachable by Tab"


@needs_node
def test_each_toggle_says_what_it_does(cond):
    """The plain-English line is the reason this was worth porting rather than reinventing.

    `local` / `hard_bid` / `prevailing_wage` are terms with money behind them and no obvious
    meaning to a new estimator; the beta's contribution was one sentence under each.
    """
    assert cond["shape"]["whyNonEmpty"], "a toggle with no explanation under it"
    assert cond["shape"]["label"] == "Dye"


# ── nobody is asked a question that cannot apply to their job ───────────────
@needs_node
def test_the_questions_follow_the_work_type(cond):
    by = cond["byWorkType"]
    # Dye, joint filler and its removal are Polish tabs cells -- an epoxy job has no polished
    # floor to dye, so asking would be asking for a number that reaches nothing.
    assert "dye" not in by["epoxy"]
    assert "joint_filler" not in by["epoxy"]
    assert "remove_existing_jf" not in by["epoxy"]
    # And the bulk discount is Epoxy!D41, so it is not a polish question.
    assert "bulk_discount" not in by["polish"]
    # A combo job is billed off both tabs, so it is asked everything.
    assert set(by["combo"]) == set(by["epoxy"]) | set(by["polish"])
    # Gyp is priced off its own tabs with none of these five cells in play.
    assert set(by["gyp"]) == {"local", "hard_bid", "prevailing_wage", "taxable", "remodel_tax"}
    assert "reno" not in by["gyp"]


@needs_node
def test_the_five_original_flags_are_asked_of_every_work_type(cond):
    """These five came off the beta page and are tab-independent, so nobody loses them."""
    five = {"local", "hard_bid", "prevailing_wage", "taxable", "remodel_tax"}
    for wt, keys in cond["byWorkType"].items():
        assert five <= set(keys), wt


# ── the defaults match the template, which is the point of them ────────────
@needs_node
def test_joint_filler_defaults_on_because_the_template_ships_it_on(cond, sheet):
    """The sharpest regression risk in this change.

    The beta's condition defaults are `local:true, taxable:true` and everything else false. Carry
    that convention to `joint_filler` and the form starts writing ``Polish!E29 = "No"`` to every
    polish job -- silently REMOVING joint filler from jobs that get it today. The template's own
    value is the authority, so it is read here rather than restated.
    """
    assert str(sheet["Polish"]["E29"].value).strip().lower() == "yes"
    assert cond["defaults"]["joint_filler"] is True


@needs_node
def test_the_other_defaults_match_the_template_too(cond, sheet):
    e = sheet["Epoxy"]
    assert cond["defaults"]["local"] is (str(e["B4"].value).strip().lower() == "yes")
    assert cond["defaults"]["hard_bid"] is (str(e["B5"].value).strip().lower() == "yes")
    assert cond["defaults"]["taxable"] is (str(e["B6"].value).strip().lower() == "yes")
    assert cond["defaults"]["prevailing_wage"] is False
    assert cond["defaults"]["remodel_tax"] is False
    assert cond["defaults"]["dye"] is (str(sheet["Polish"]["E25"].value).strip().lower() == "yes")
    assert cond["defaults"]["remove_existing_jf"] is (
        str(sheet["Polish"]["F29"].value).strip().lower() == "yes")


# ── picking a work type is not, by itself, an edit ─────────────────────────
@needs_node
def test_choosing_a_work_type_on_a_blank_form_writes_nothing(cond):
    """Ten flags on a project with no name yet is a row nobody asked to create.

    It also matters to the test next door: `test_beta_intake_routing.py` counts saves to prove the
    beta button is not a way round the required-field check, and an ambient write fired by a radio
    would read as exactly that.
    """
    assert cond["savesOnWorkTypeAlone"] == 0
    assert cond["cellsOnWorkTypeAlone"] == 0


# ── the literals that land in the sheet ────────────────────────────────────
@needs_node
def test_a_flip_writes_the_cell_and_saves_once(cond):
    cells = cond["afterDyeOn"]
    assert cells["Polish!E25"] == "Yes"
    assert cond["dyeSaves"] == 1, "one flip, one save"
    assert cond["dyeSwitchNowOn"] is True
    assert cond["dyeAriaNowTrue"] == "true", "a screen reader has to hear the change too"


@needs_node
def test_local_and_hard_bid_reach_both_tabs(cond, sheet):
    """`Polish!B4`/`B5` hold their OWN Yes/No, unlike the three below them."""
    p = sheet["Polish"]
    assert not str(p["B4"].value).startswith("="), "if B4 became a formula, stop writing it"
    assert not str(p["B5"].value).startswith("=")
    cells = cond["afterDyeOn"]
    assert cells["Epoxy!B4"] == cells["Polish!B4"] == "Yes"
    assert cells["Epoxy!B5"] == cells["Polish!B5"] == "No"


@needs_node
def test_the_three_flags_polish_mirrors_are_never_written_to_the_polish_tab(cond, sheet):
    """And the workbook says why.

    `Polish!D5`, `B6` and `D6` are the formulas ``=Epoxy!D5`` / ``=Epoxy!B6`` / ``=Epoxy!D6``.
    Writing a literal into one of those replaces a live reference and decouples the two tabs
    permanently -- from then on a prevailing-wage job would be prevailing wage on the epoxy side
    and not on the polish side, with nothing on screen to show it. So the polish tab follows on
    its own for all three.

    RULE CHANGED 2026-09-05, deliberately, and this test used to be called
    ``..._are_written_to_epoxy_only``. "Not written to Polish" was true; "Epoxy-only" was not.
    ``Taxable?`` is an independent LITERAL on ``Leveling!B6``, ``'Gyp (USG 1-8")'!B8`` and
    ``'Gyp (FR)'!B8`` as well, each read by its own sheet's ``=IF($B$6="no",0,0.09475)``, and
    writing Epoxy alone left every tax-exempt gypsum and Leveling bid carrying 9.475%. The four
    cells are pinned against the workbook in
    ``test_taxable_flag_reaches_every_sheet.py::test_the_intake_writes_the_answer_to_all_four_literal_cells``.

    Prevailing wage and remodel tax are still genuinely Epoxy-only: ``Epoxy!D5`` and ``Epoxy!D6``
    are the only literals either one has anywhere in the workbook.
    """
    p = sheet["Polish"]
    for addr, ref in (("D5", "=Epoxy!D5"), ("B6", "=Epoxy!B6"), ("D6", "=Epoxy!D6")):
        assert p[addr].value == ref, (
            "Polish!%s is no longer a mirror of the Epoxy cell -- if Kyle made it independent, "
            "these three need writing to both tabs like B4/B5" % addr)
    cells = cond["afterDyeOn"]
    for addr in ("Polish!D5", "Polish!B6", "Polish!D6"):
        assert addr not in cells, addr + " must never be written -- it is a formula"
    assert cells["Epoxy!D5"] == "No"
    assert cells["Epoxy!B6"] == "Yes"
    assert cells["Epoxy!D6"] == "No"
    # Prevailing wage and remodel really are one cell each -- every other sheet's is =Epoxy!.
    for addr in cells:
        assert not addr.endswith("!D5") or addr == "Epoxy!D5", addr
        assert not addr.endswith("!D6") or addr == "Epoxy!D6", addr
    # ...while Taxable now reaches all four of the cells that hold it independently.
    assert cells["Leveling!B6"] == "Yes"
    assert cells['Gyp (USG 1-8")!B8'] == "Yes"
    assert cells["Gyp (FR)!B8"] == "Yes"
    for addr in ("Gyp (USG N12ULTRA)!B8", 'Gyp (USG N25 1-4")!B8', "Gyp (GWorx SC190)!B8",
                 "Seal!B6", "Seal (+Jnts)!B6", "Epoxy blank!B6"):
        assert addr not in cells, addr + " must never be written -- it is a formula"


@needs_node
def test_renovation_off_writes_new_and_never_a_blank(cond):
    """The trap this file mostly exists for.

    ``Polish!C17 = IF(B10="New",0.05,0.15)``. A blank `B10` is not "New" -- it takes the RENO
    branch and triples the patch material rate. So *off* has to write the word, and the key has to
    still be there.
    """
    r = cond["reno"]
    assert r["on"] == "Reno"
    assert r["off"] == "New"
    assert r["offIsPresent"] is True, "an absent B10 prices as Reno -- write the word"
    assert r["onPolish"] == "Reno" and r["offPolish"] == "New"
    assert r["bothTabs"] is True, "B10 exists on both tabs and both are billed from"


@needs_node
def test_renovation_writes_one_of_the_two_words_the_dropdown_offers(cond, sheet):
    """`B10` is a string, not a boolean, and the two strings are Kyle's."""
    listed = set()
    for dv in sheet["Epoxy"].data_validations.dataValidation:
        if "B10" in str(dv.sqref) and dv.formula1:
            listed |= {x.strip().strip('"') for x in dv.formula1.strip('"').split(",")}
    if listed:
        assert {cond["reno"]["on"], cond["reno"]["off"]} <= listed, (
            "the toggle writes something the dropdown does not offer: %s" % sorted(listed))


@needs_node
def test_the_bulk_discount_matches_kyles_own_comparison_cells(cond, sheet):
    """Read out of the workbook, because a typo here fails silently and costs money.

    All six consumers are ``IF($D$41=$V$136,...)`` comparisons. `V136`/`V137` are
    ``BULK Discount ON`` / ``Bulk Discount OFF`` -- mixed case, and not even consistent with each
    other, which is exactly why this is not asserted against a hand-typed string.
    """
    e = sheet["Epoxy"]
    on, off = e["V136"].value, e["V137"].value
    assert cond["bulkOn"] == on, "must equal Epoxy!V136 byte for byte, or the discount is skipped"
    assert cond["bulkOff"] == off
    assert on != off.upper() and on != off, "sanity: the two literals really are different"


# ── a question that no longer applies stops writing ───────────────────────
@needs_node
def test_retyping_the_job_drops_the_cells_that_no_longer_apply(cond):
    """A polish job switched to epoxy must not carry ``Polish!E25 = "Yes"`` into a bid with no
    polish in it. The two Continue handlers already apply this reasoning to the gyp SF buckets."""
    c = cond["scopeCleanup"]
    assert "Polish!E25" in c["before"] and "Polish!E29" in c["before"]
    assert c["polishGone"] is True
    assert c["epoxyKept"] == "Yes", "and the tab-independent flags survive the change"
    assert "Epoxy!D41" in c["after"], "epoxy now asks about bulk, so it now answers"


@needs_node
def test_a_draft_that_already_carries_these_cells_does_get_cleaned_up(cond):
    """The other half of the save rule.

    Nothing is written for an untouched form -- but once a cell IS in play, whether from a flip
    here, the estimate grid, or the AI autofill's seven flags, a work-type change has to sweep the
    stale ones out. Otherwise the "writes nothing on a blank form" rule would also mean "never
    cleans up", which is the bug.
    """
    assert cond["seededCleanup"]["saves"] == 1
    assert cond["seededCleanup"]["dyeGone"] is True


# ── cell_values is shared, so a flip must not stamp on the rest of it ─────
@needs_node
def test_a_flip_merges_into_cell_values_and_drops_nothing(cond):
    """`cell_values` also carries the AI autofill's flags and every cell the estimator typed by
    hand on the estimate grid. A fresh object here would silently discard all of it."""
    assert cond["merged"] == {"Epoxy!E20": 4200, "Polish!E19": 3100}


# ── coming back to the form shows what the sheet says ────────────────────
@needs_node
def test_the_switches_are_read_back_off_the_sheet_not_off_a_key_of_our_own(cond):
    """Hydration, and it has three separate jobs.

    A draft returning through Back, a flag the AI autofill set, and a value the estimator typed
    straight into the estimate grid all arrive the same way -- as a cell. Reading the switch state
    back out of `cell_values` is what makes all three show correctly, and it is why these toggles
    write there rather than into `polish_estimate` (whose `version == 2` is the only flag routing a
    project to the beta calculator, so writing conditions in there forces a fork with no safe
    default either way).
    """
    h = cond["hydrated"]
    assert h["taxable"] is False, "the draft said No; the default said Yes; the draft wins"
    assert h["dye"] is True
    assert h["joint_filler"] is False, "an explicit No has to beat the template's Yes"
    assert h["local"] is False, "and a lower-case 'no' off the grid still reads as off"
    assert h["hard_bid"] is False and h["remodel_tax"] is False, "unset ones keep their default"


@needs_node
def test_arriving_on_a_draft_that_has_these_cells_does_not_rewrite_them_twice(cond):
    """One save on arrival -- the work-type cleanup -- and not a second from hydration itself."""
    assert cond["hydrateSaves"] == 1


# ── the inert row, rather than a vanishing one ────────────────────────────
@needs_node
def test_removing_existing_filler_goes_inert_when_there_is_no_filler(cond):
    """Its sole consumer is ``Polish!A42 = IF(F29="NO",3,4)`` -- the joint-filler crew size. With
    joint filler off there is no crew for it to add a hand to.

    Said plainly rather than hidden, which is the county picker's own precedent: tell the
    estimator an input is not affecting the price instead of removing it and losing what was set.
    """
    i = cond["inert"]
    assert i["beforeInert"] is False
    assert i["afterInert"] is True
    assert i["afterStillRendered"] is True, "hiding it loses the setting; grey it out instead"
    assert "not affecting the price" in i["afterWhy"].lower()
    assert "joint filler" in i["afterWhy"].lower(), "and name what has to change to fix it"


# ── the keyboard, which the beta advertised and never wired ──────────────
@needs_node
def test_space_and_enter_operate_a_focused_switch(cond):
    k = cond["keyboard"]
    assert k["handlers"] == 1, "no keydown listener at all -- Space and Enter do nothing"
    assert k["onAfterSpace"] is True, "Space did not flip it"
    assert k["onAfterEnter"] is False, "Enter did not flip it back"
    assert k["cellAfterSpace"] == "Yes", "the key press has to write the cell, not just repaint"
    assert k["savesAfterSpace"] == 1


@needs_node
def test_space_does_not_also_scroll_the_page(cond):
    """`preventDefault` on Space specifically -- without it the page jumps a screen on every
    toggle, which is worse than no keyboard support at all."""
    assert cond["keyboard"]["spacePrevented"] is True
    assert cond["keyboard"]["enterPrevented"] is True


@needs_node
def test_an_ordinary_letter_is_left_alone(cond):
    """The listener is delegated on the whole box, so a greedy handler would eat typing."""
    assert cond["keyboard"]["letterPrevented"] is False
    assert cond["keyboard"]["onAfterLetter"] is False


@needs_node
def test_the_switch_keeps_focus_across_the_re_render(cond):
    """`toggleCondition` rebuilds the entire box -- turning joint filler off has to grey out the
    removal row and say why, which is a second node. Without putting focus back, a keyboard user
    is thrown to the top of the page on every single press."""
    assert cond["focusKept"] is True


# ── a stray data-cond invents nothing ────────────────────────────────────
@needs_node
def test_a_click_naming_a_condition_this_job_was_never_asked_writes_nothing(cond):
    """Defence in depth for the delegated listener: the guard is on the condition's scope, not on
    what happens to be in the markup, so stale DOM cannot write a cell for an epoxy job's
    non-existent dye."""
    assert cond["strayCond"]["saves"] == 0
    assert cond["strayCond"]["dyeWritten"] is False


# ── and none of the ten are locked in the generated file ────────────────
def test_none_of_these_cells_are_locked_against_the_estimator(sheet):
    """They are set on intake, and the estimator has to be able to change any of them in the
    workbook afterwards -- `estimate_writer.LOCK_MAP` is what would stop that."""
    import estimate_writer
    locked = set()
    for tab, addrs in getattr(estimate_writer, "LOCK_MAP", {}).items():
        for a in addrs:
            locked.add("%s!%s" % (tab, a))
    ours = {"Epoxy!B4", "Epoxy!B5", "Epoxy!D5", "Epoxy!B6", "Epoxy!D6", "Epoxy!B10", "Epoxy!D41",
            "Polish!B4", "Polish!B5", "Polish!B10", "Polish!E25", "Polish!E29", "Polish!F29",
            # The three Taxable cells added 2026-09-05. Same rule, same reason: the estimator has
            # to be able to change a tax answer in the workbook after it is downloaded.
            "Leveling!B6", 'Gyp (USG 1-8")!B8', "Gyp (FR)!B8"}
    assert not (ours & locked), sorted(ours & locked)
