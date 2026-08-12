"""The Follow-ups checkbox sits OUTSIDE the bordered recipient row, to the right of Edit.

Hanz, 2026-08-13, with a screenshot of the Done page's RECIPIENTS block:
"ccan you put the follow up checkbox to the right of edit outside the container?"

Before this, one bordered row held email → Follow-ups → INTAKE → Edit, so a decision ABOUT the
recipient looked like one of the recipient's own fields. Now each entry is a wrapper holding the
bordered row and, beside it, the checkbox.

WHY THIS IS EXECUTED RATHER THAN GREPPED. The claim is purely structural — "outside the
container" — and `wrap.appendChild(fu)` appearing in the source says nothing about where the
node lands: the same line inside the wrong block, or a wrap that is itself inside the row,
would read identically. So the harness renders the real `mountPortalRecipients` against a DOM
shim and walks the actual parent/child relationships.

The opt-out plumbing is asserted alongside the layout on purpose. Moving a control is exactly
when its wiring gets left behind, and this particular control decides whether a customer gets
chased — a checkbox that renders in the right place and no longer records anything would be a
worse outcome than the layout nobody liked.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "recipients-row-harness.js"
DONE_HTML = (FRONTEND / "done.html").read_text(encoding="utf-8")

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


# ── the ask ──────────────────────────────────────────────────────────────────
@needs_node
def test_the_checkbox_is_not_inside_the_bordered_row(ran):
    """The whole request, in one assertion."""
    for w in ran["intakeOnly"] + ran["twoWithOptOut"]:
        assert w["fuIsInsideRow"] is False, (
            "the Follow-ups control is still a descendant of .tw-em-row: %s" % w)


@needs_node
def test_the_checkbox_is_a_sibling_that_comes_AFTER_the_row(ran):
    """"to the right of edit" — after the row in document order, not before it, or it would
    render on the left of the border instead."""
    for w in ran["intakeOnly"] + ran["twoWithOptOut"]:
        assert w["fuIsDirectChildOfWrap"] is True, w
        assert w["fuAfterRow"] is True, (
            "the checkbox renders before the bordered row: %s" % w["childClasses"])
        assert w["childClasses"] == ["tw-em-row", "tw-em-fu"], w["childClasses"]


@needs_node
def test_the_bordered_row_still_holds_the_email_tag_and_edit(ran):
    """What stays inside the container. The intake row keeps its tag and Edit button; an extra
    keeps its remove ×. Losing one of those in a layout change is silent."""
    intake = ran["intakeOnly"][0]["rowChildren"]
    assert intake == ["em", "tw-em-tag", "tw-em-editbtn"], intake
    extra = ran["twoWithOptOut"][1]["rowChildren"]
    assert extra == ["em", "tw-em-x"], extra


# ── the wiring that must survive the move ────────────────────────────────────
@needs_node
def test_the_opt_out_state_still_drives_the_checkbox(ran):
    """A ticked box means "this contact gets chased". The extra in the fixture is opted out and
    its box must render UN-ticked — a control in the right place that shows the wrong state is
    worse than the old layout."""
    assert ran["intakeOnly"][0]["fuChecked"] is True
    both = ran["twoWithOptOut"]
    assert both[0]["fuChecked"] is True, "the intake contact should be chased by default"
    assert both[1]["fuChecked"] is False, "the opted-out extra renders as ticked"


@needs_node
def test_editing_an_address_offers_no_follow_ups_control(ran):
    """Mid-edit there is no settled recipient to attach the decision to. Asserted through the
    row composition above: the edit path appends input + Save + Cancel and nothing else."""
    for w in ran["editing"]:
        assert w["fuIsDirectChildOfWrap"] is False and w["fuIsInsideRow"] is False, (
            "the edit-mode entry rendered a follow-ups control: %s" % w)
        assert w["rowChildren"] == ["em", "tw-em-editbtn", "tw-em-editbtn"], w["rowChildren"]


@needs_node
def test_an_empty_recipient_list_grows_no_stray_control(ran):
    """No customer email on file is a real state ("No customer email on file — add one below").
    It must not sprout a checkbox belonging to nobody."""
    rows = ran["noIntake"]
    assert len(rows) == 1 and rows[0]["className"] == "tw-em-empty", rows
    assert rows[0]["fuIsDirectChildOfWrap"] is False


# ── the layout has to hold up, not just exist ────────────────────────────────
def test_the_wrapper_is_styled_so_the_row_keeps_its_width():
    """Without `flex: 1` on the row the border shrink-wraps the email and the checkbox floats in
    from the middle of the line — visually worse than where it started."""
    # The RULE BODY, not a character window. A 400-char slice reached into the neighbouring
    # `.tw-em-row` rule — which has its own `display: flex` — so a mutation setting the wrapper
    # to `display: block` sailed through. Same trap as the "isTest in the first 2000 characters"
    # assertion fixed on 2026-08-12: counting characters to infer structure cries wolf, or worse,
    # stays silent.
    wrap = re.search(r"\.tw-em-rowwrap \{([^}]*)\}", DONE_HTML)
    assert wrap, "the wrapper has no styling at all"
    assert "display: flex" in wrap.group(1), (
        "the wrapper is not a flex row, so the checkbox drops below the recipient: %r"
        % wrap.group(1).strip())
    row = re.search(r"\.tw-em-rowwrap > \.tw-em-row \{([^}]*)\}", DONE_HTML)
    assert row, "the bordered row has no rule inside the wrapper"
    assert "flex: 1" in row.group(1), "the row does not stretch, so the checkbox drifts left"
    assert "min-width: 0" in row.group(1), (
        "without min-width the long-email ellipsis stops working inside a flex child")
