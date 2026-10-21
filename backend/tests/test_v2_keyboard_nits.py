"""ROUND 7 POLISH (2026-10-22): TWO KEYBOARD NITS FROM THE REAL-BROWSER WALK OF STAGING, on the real estimate page (tests/js/keyboard-nits-harness.js runs js/polish-estimate.js over the real
js/bid-model.js). Neither moves a price; both are about where the caret is after a key.

  K1 (X1)  ESCAPE ON THE SHEETS PANEL'S "ADD A SHEET" LIST did nothing: only the rename box took Escape, and the list's Close button was a click and nothing else. Escape on a control of the panel
           while the list is open closes it, puts the caret back on the "Add sheet" button that opened it (sheetsUi.focus = "add|menu") and is prevented. Not while the list is shut, not for a key
           pressed outside the panel, and never over a key something else took: the rename box's Escape cancels the rename and leaves the list open for a second Escape.
  K2 (X2)  THE CARET FOLLOWS A STEP THAT WAS PRESSED. Next, Back, a step on the rail and Edit on a Review card rebuild the panel and the rail, so the button that had the caret was gone and focus fell to
           <body>: the next Tab started again from the top of the page, through the sheet strip and the sidebar. The new step's heading takes it (tabindex -1, focused with preventScroll so the page does
           not jump past the scroll to the top that go() asks for on purpose). Opening the page and a step set by a script take no caret.
"""
from __future__ import annotations

import pathlib

import pytest

from _golden_support import FRONTEND, break_source, copy_unmodified
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "keyboard-nits-harness.js"
SECTIONS = ("escape", "steps")
PAGE_FILES = ["polish-estimate.html", "js/polish-estimate.js", "js/bid-model.js", "js/bid-engine.js", "js/bid-profiles.js",
              "js/markup-core.js", "js/library-core.js", "js/library-picker.js", "js/work-types.js", "js/excel-math.js",
              "js/epoxy-takeoff.js", "js/gyp-takeoff.js", "js/seal-takeoff.js", "js/price-lines-core.js"]

SHUT = {"open": False, "expanded": "false"}
OPEN = {"open": True, "expanded": "true"}


def caret(key):
    """One focus() call on the panel's control `key`, never scrolling (the bar is in the sticky head: a plain focus() would throw a scrolled page up to it)."""
    return [{"key": key, "noScroll": True}]


def heading(text):
    """One focus() call on the step's heading: made focusable first (tabindex -1), and told not to scroll."""
    return [{"tag": "h2", "text": text, "tabindex": "-1", "noScroll": True}]


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the harness itself failed:\n" + proc.stderr[-1500:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    got = run()
    for k in SECTIONS:
        assert "error" not in got[k], "%s threw: %s" % (k, got[k]["error"][:600])
    return got


# ── K1: Escape on the "Add a sheet" list ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_list_is_shut_and_opening_it_puts_the_caret_on_its_close_button(ran):
    """The premise, which the page already kept: the list starts shut, and opening it puts the caret on its Close button."""
    e = ran["escape"]
    assert e["shut"] == SHUT
    assert e["opened"] == {"state": OPEN, "focus": caret("add|close")}


def test_escape_on_the_open_list_closes_it_puts_the_caret_back_on_add_sheet_and_is_taken(ran):
    """Escape on the Close button, and on one of the list's own rows: the list is gone, the button that opens it is marked shut again and has the caret, and the key is prevented."""
    e = ran["escape"]
    shut_again = {"state": SHUT, "focus": caret("add|menu"), "prevented": True}
    assert e["closed"] == shut_again
    assert e["fromRow"] == shut_again


def test_escape_is_left_alone_while_the_list_is_shut_for_another_key_and_outside_the_panel(ran):
    """Escape with the list shut is not the page's to swallow: nothing moves and it is not prevented. Another key does not close the list, and Escape pressed outside the panel (a button of the
    step) leaves it open and unprevented."""
    e = ran["escape"]
    assert e["shut2"] == {"state": SHUT, "focus": [], "prevented": False}
    assert e["otherKey"] == {"state": OPEN, "focus": [], "prevented": False}
    assert e["outside"] == {"state": OPEN, "focus": [], "prevented": False}


def test_the_rename_boxes_escape_takes_the_key_first_and_the_list_closes_on_the_second(ran):
    """Rename open beside the open list: the first Escape (in the name box) cancels the rename, puts the caret back on Rename, is prevented, and leaves the list open; the second closes the list.
    One Escape, one level: a key a listener has taken is not taken again."""
    r = ran["escape"]["renameFirst"]
    assert r["first"] == {"renamingBefore": True, "renaming": False, "state": OPEN, "focus": caret("Polish|rename"), "prevented": True}
    assert r["second"] == {"state": SHUT, "focus": caret("add|menu"), "prevented": True}


# ── K2: the caret follows a step that was pressed ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_opening_the_page_and_a_step_set_by_a_script_take_no_caret(ran):
    """The page opens on its step and nobody has pressed anything, so the caret is left where the browser put it; go() is the page's own move to a step (it scrolls to the top on purpose) and takes none."""
    s = ran["steps"]
    assert s["onOpen"] == []
    assert s["byScript"] == {"at": 1, "focus": []}


def test_next_back_the_rail_and_a_review_cards_edit_put_the_caret_on_the_new_steps_heading(ran):
    """Each press lands on its step and the new step's heading takes the caret: made focusable (tabindex -1) and told not to scroll. Next on Material goes to Labor, Back to Material, the rail's Review
    button to the Review (Review the bid), Edit on its Material card back to Material, and the rail's first button to Material."""
    s = ran["steps"]
    assert s["next"] == {"what": "next", "at": 1, "focus": heading("Labor")}
    assert s["back"] == {"what": "back", "at": 0, "focus": heading("Material")}
    assert s["rail"] == {"what": "rail", "at": 2, "focus": heading("Review the bid")}
    assert s["edit"] == {"what": "edit", "at": 0, "focus": heading("Material")}
    assert s["railBack"] == {"what": "railBack", "at": 0, "focus": heading("Material")}


# ── red without the code: break a COPY of the page one line at a time; a fact must change, never a crash ────────────────────────────────────────────────────────────────
ESC_GUARD = '    if (e.key !== "Escape" || !sheetsUi.pick || e.defaultPrevented || !t || !t.closest || !t.closest("[data-sh-key]")) return;'
ESC_ACT = '    e.preventDefault(); sheetsAct("add-close");'
RAIL_CALL = '      b.addEventListener("click", function () { go(i); focusStepHeading(); });'
GO_CALL = '    if (go_) { e.preventDefault(); go(parseInt(go_.getAttribute("data-go"), 10)); focusStepHeading(); return; }'
HEAD_PICK = '    var panels = $("panels"), head = panels ? panels.querySelector("h2") : null;'

BREAKS = {
    # --- K1 ---
    "the page listens for another key": (
        "js/polish-estimate.js", ESC_GUARD, ESC_GUARD.replace('e.key !== "Escape"', 'e.key !== "Enter"'),
        lambda g: g["escape"]["closed"]["state"] != SHUT or g["escape"]["fromRow"]["state"] != SHUT),
    "escape closes a list that is shut": (
        "js/polish-estimate.js", ESC_GUARD, ESC_GUARD.replace(' || !sheetsUi.pick', ""),
        lambda g: g["escape"]["shut2"] != {"state": SHUT, "focus": [], "prevented": False}),
    "escape takes a key something else took": (
        "js/polish-estimate.js", ESC_GUARD, ESC_GUARD.replace(" || e.defaultPrevented", ""),
        lambda g: g["escape"]["renameFirst"]["first"]["state"] != OPEN),
    "escape from outside the panel closes the list": (
        "js/polish-estimate.js", ESC_GUARD, ESC_GUARD.replace(' || !t || !t.closest || !t.closest("[data-sh-key]")', ""),
        lambda g: g["escape"]["outside"] != {"state": OPEN, "focus": [], "prevented": False}),
    "escape closes the list and leaves the key": (
        "js/polish-estimate.js", ESC_ACT, '    sheetsAct("add-close");',
        lambda g: g["escape"]["closed"]["prevented"] is not True),
    "escape takes the key and leaves the list": (
        "js/polish-estimate.js", ESC_ACT, "    e.preventDefault();",
        lambda g: g["escape"]["closed"]["state"] != SHUT or g["escape"]["closed"]["focus"] != caret("add|menu")),
    # --- K2 ---
    "a step on the rail takes no caret": (
        "js/polish-estimate.js", RAIL_CALL, '      b.addEventListener("click", function () { go(i); });',
        lambda g: g["steps"]["rail"]["focus"] != heading("Review the bid") or g["steps"]["railBack"]["focus"] != heading("Material")),
    "Next, Back and Edit take no caret": (
        "js/polish-estimate.js", GO_CALL, '    if (go_) { e.preventDefault(); go(parseInt(go_.getAttribute("data-go"), 10)); return; }',
        lambda g: g["steps"]["next"]["focus"] != heading("Labor") or g["steps"]["back"]["focus"] != heading("Material") or g["steps"]["edit"]["focus"] != heading("Material")),
    "the heading is focused with a scroll": (
        "js/polish-estimate.js", "    head.focus({ preventScroll: true });", "    head.focus();",
        lambda g: g["steps"]["next"]["focus"] != heading("Labor")),
    "the heading is focused without being made focusable": (
        "js/polish-estimate.js", '    head.setAttribute("tabindex", "-1");', "    void head;",
        lambda g: g["steps"]["next"]["focus"] != heading("Labor")),
    "the caret goes to something that is not the heading": (
        "js/polish-estimate.js", HEAD_PICK, HEAD_PICK.replace('querySelector("h2")', 'querySelector("section")'),
        lambda g: g["steps"]["next"]["focus"] != heading("Labor")),
    "a step set by a script takes the caret": (
        "js/polish-estimate.js", "    window.scrollTo({ top: 0, behavior: \"smooth\" });", "    window.scrollTo({ top: 0, behavior: \"smooth\" }); focusStepHeading();",
        lambda g: g["steps"]["byScript"]["focus"] != []),
}


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_scenarios_go_red_when_the_page_changes(tmp_path, name):
    """Each change is a line this file depends on, broken in a scratch copy of the page; a FACT must change. A break that stops the harness, or makes a section throw, is not counted as noticed: it has
    no facts to compare."""
    require_node()
    rel, old, new, noticed = BREAKS[name]
    frontend = break_source(tmp_path, rel, old, new)
    copy_unmodified(frontend, PAGE_FILES)
    proc = run_node(HARNESS, frontend)
    assert proc.returncode == 0, "the break stopped the harness outright, so no fact noticed it: " + name + "\n" + proc.stderr[-600:]
    got = last_json_line(proc.stdout)
    crashed = sorted(k for k in SECTIONS if "error" in got.get(k, {}))
    assert not crashed, "the break crashed %s instead of changing a fact: %s" % (", ".join(crashed), name)
    assert noticed(got), "the scenarios did not notice: " + name
