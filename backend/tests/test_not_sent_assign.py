"""Assign an estimator to a project that has not been sent, and have the Files screen agree.

Hanz, 2026-08-13: "Allow to choose the estimator on the Created but not sent", and then "that
estimator picker should also reflect in the Section 4 of the estimate."

The card and the drawer both showed a name with a question mark after it — "Kyle?" — because
`estimatorOf` falls back to the draft's AUTHOR when nobody has been assigned. That is the honest
thing to display, and the drawer was the one place that displayed the guess while offering no way
to settle it. The Projects tab could assign; the CRM drawer could not.

Two things had to be true for the second half of the ask:

* the picker writes the DRAFT's copy (`POST /api/draft/{id}/assign`), because an unsent project has
  no portal row to assign against — and the draft's copy is exactly what the Files screen reads;
* the Files screen has to re-read it. The full state hydrate only runs when the local blob belongs
  to a DIFFERENT draft, so assigning in the CRM and then opening the same project's Files screen on
  the same machine skipped it and the picker read a copy from before the assignment.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "not-sent-assign-harness.js"
PORTAL_JS = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
SHARED_JS = (FRONTEND / "shared.js").read_text(encoding="utf-8")
DONE_JS = (FRONTEND / "js" / "done.js").read_text(encoding="utf-8")
PORTAL_HTML = (FRONTEND / "portal.html").read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def drawer():
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the control ───────────────────────────────────────────────────────────────
def test_the_drawer_offers_a_picker(drawer):
    o = drawer["offered"]
    assert o["hasSelect"] and o["hasButton"], o
    assert o["startsDisabled"] is True, (
        "the select is usable before the roster has loaded, so it can be left showing 'Loading…'")


def test_the_existing_actions_are_untouched(drawer):
    """The drawer's job is still to open the files or edit the estimate."""
    assert drawer["offered"]["unchangedActions"] is True


def test_the_picker_is_actually_visible(drawer):
    """Rendered is not the same as reachable. A `hidden` wrapper still emits every id, so the
    harness would resolve `#ns-assign`, wire it, and report a working control that nobody can see
    — a mutation proved exactly that before this assertion existed."""
    assert drawer["offered"]["pickerHidden"] is False


def test_the_estimator_is_named_once(drawer):
    """The whole job of the redesign merge. Two renderers of that line existed for a few minutes —
    the redesign's facts grid and this feature's own section — and they would have drifted the
    first time either changed how an unassigned estimator reads."""
    assert drawer["offered"]["estimatorCells"] == 1, (
        "the estimator is rendered %s times" % drawer["offered"]["estimatorCells"])


def test_the_guess_is_still_shown_with_its_question_mark(drawer):
    """The picker settles the question; it does not hide that nobody has answered it. Replacing
    the name with a bare control would lose the one useful fact on the panel."""
    assert drawer["offered"]["stillShowsTheGuess"] is True


def test_an_unassigned_project_does_not_pre_select_the_author(drawer):
    """THE point of the "?". Pre-selecting the guess would let one click on Assign promote
    "whoever built this" into "whoever owns this", which is a decision nobody made."""
    u = drawer["unassigned"]
    assert u["value"] == "", u
    assert u["offersChoose"] is True
    assert u["enabled"] is True, "the control never became usable"


def test_an_assigned_project_pre_selects_the_assignee(drawer):
    a = drawer["assigned"]
    assert a["value"] == "rj@wetreadwell.com"
    assert a["noChoosePrompt"] is True, (
        "an assigned project still offers 'Choose an estimator…', which reads as unassigned")


def test_somebody_who_has_left_the_roster_stays_listed(drawer):
    """Dropping them silently would make the control read as unassigned, and the next Save would
    quietly reassign a project nobody meant to touch."""
    d = drawer["departed"]
    assert d["value"] == "gone@wetreadwell.com"
    assert d["listed"] is True


def test_a_roster_that_will_not_load_says_so_and_sends_nothing(drawer):
    r = drawer["rosterDown"]
    assert "Unavailable" in r["says"]
    assert "reload" in r["note"].lower()
    assert r["requests"] == 0


# ── the save ──────────────────────────────────────────────────────────────────
def test_it_assigns_through_the_DRAFT_endpoint(drawer):
    """Not the portal one the sent drawer uses: there is no portal row for a project nobody has
    sent, and the draft's copy is what the Files screen and the first send read."""
    s = drawer["save"]
    assert s["path"] == "/api/draft/d-77/assign", s["path"]
    assert s["method"] == "POST"
    assert s["body"] == {"estimator_email": "rj@wetreadwell.com"}, s["body"]


def test_the_drawer_shows_the_name_it_just_saved(drawer):
    """renderNotSent is signature-guarded against the 12s poll, and the row in hand still carries
    the old assignment — so this only works because the handler clears the guard and re-renders
    with the new value. Executed against both real functions in one closure, sharing the real
    guard, because that is the only way the guard can be observed at all."""
    assert drawer["save"]["showsNewName"] is True


def test_the_board_is_refreshed_too(drawer):
    """The card behind the drawer prints the estimator; leaving it stale is how two views of one
    project end up disagreeing on screen at the same time."""
    assert drawer["save"]["refreshedBoard"] is True


def test_pressing_assign_with_nothing_chosen_sends_nothing(drawer):
    assert drawer["noChoice"]["requests"] == 0


def test_a_failed_save_says_so_and_does_not_claim_the_change(drawer):
    f = drawer["failed"]
    assert "Couldn't save" in f["note"], f["note"]
    assert f["buttonUsableAgain"] is True
    assert f["claimsSuccess"] is False, (
        "the drawer painted a name the server never stored")


# ── reaching the Files screen ("Section 4") ───────────────────────────────────
def test_the_files_screen_re_reads_the_server_owned_keys():
    """The second half of the ask. `mountEstimatorPicker` reads local state, and local state is not
    re-hydrated for a draft the browser already holds — so the CRM's assignment was invisible
    exactly when it mattered most (assign, then click "Open the files")."""
    i = DONE_JS.index("async function mountEstimatorPicker()")
    body = DONE_JS[i:i + 900]
    assert "TW.refreshServerOwned()" in body, (
        "the picker no longer re-reads the assignment, so a CRM assignment will not show here")
    assert body.index("refreshServerOwned") < body.index("TW.getState()"), (
        "the refresh runs after the state read, which makes it pointless")


def test_the_refresh_only_touches_keys_the_SERVER_owns():
    """A wide merge would overwrite what the estimator has typed on this page. The list mirrors
    `_SERVER_OWNED_KEYS` in backend/drafts.py, which is what protects these keys from being
    clobbered by an autosave in the other direction."""
    m = re.search(r"const SERVER_OWNED_KEYS = \[([^\]]*)\]", SHARED_JS)
    assert m, "SERVER_OWNED_KEYS moved"
    keys = {k.strip().strip('"\'') for k in m.group(1).split(",") if k.strip()}
    assert keys == {"assigned_estimator", "is_test", "archived"}, keys
    backend = (pathlib.Path(__file__).resolve().parents[1] / "drafts.py").read_text(encoding="utf-8")
    b = re.search(r"_SERVER_OWNED_KEYS = \(([^)]*)\)", backend)
    assert b, "_SERVER_OWNED_KEYS moved in drafts.py"
    assert {k.strip().strip('"\'') for k in b.group(1).split(",") if k.strip()} == keys, (
        "the two lists disagree: a key the server owns on one side is client-owned on the other")


def test_the_refresh_is_exported_and_cannot_write_over_local_work():
    assert "refreshServerOwned," in SHARED_JS, "TW.refreshServerOwned is not exported"
    i = SHARED_JS.index("async function refreshServerOwned()")
    body = SHARED_JS[i:SHARED_JS.index("\n  // The most recent server write", i)]
    # Only the named keys are copied, and only when the server actually has them.
    assert "hasOwnProperty.call(data, k)" in body, (
        "a key the server has never set would be merged as undefined")
    assert "if (moved.length) setState(patch)" in body, (
        "state is written unconditionally, which marks the blob dirty on every page load")
    assert "isUnverified(id)" in body, (
        "a draft we could not read is re-read anyway, risking a merge over unsaved local work")


def test_a_failed_refresh_leaves_the_page_alone():
    i = SHARED_JS.index("async function refreshServerOwned()")
    body = SHARED_JS[i:SHARED_JS.index("\n  // The most recent server write", i)]
    assert "catch {\n      return {};" in body, (
        "a blip in this fetch can now break the Files screen")
    assert "if (!res.ok) return {};" in body


def test_the_picker_still_starts_blank_when_nobody_has_assigned():
    """Assigning from the CRM must pre-select; an unassigned project must not. Both live on the
    same line, so the comment above it is load-bearing and the behaviour is worth pinning."""
    i = DONE_JS.index("async function mountEstimatorPicker()")
    body = DONE_JS[i:i + 2600]
    assert 'const prev = String(st.assigned_estimator || "").toLowerCase();' in body
    assert "if (prev && list.some(" in body, (
        "the pre-selection no longer checks the roster, so a departed estimator would blank it")


# ── the styling exists ────────────────────────────────────────────────────────
def test_the_control_is_styled():
    """A flex row with no rule is a select and a button stacked oddly in a 380px drawer.

    `.ns-est` is deliberately gone: the 2026-08-13 redesign renders the estimator as a `fact` in
    the panel's facts grid, so the picker no longer draws the name itself. One renderer for that
    line, not two that can drift."""
    assert ".ns-assign {" in PORTAL_HTML
    assert ".ns-est" not in PORTAL_HTML, (
        "dead rule: the facts grid draws the estimator now")
    rule = re.search(r"\.ns-assign \{([^}]*)\}", PORTAL_HTML).group(1)
    assert "flex" in rule, rule
    assert ".ns-assign-note:empty { display:none; }" in PORTAL_HTML, (
        "the error line reserves space even when there is no error")


def test_the_drawer_wires_the_picker_on_every_render():
    """renderNotSent rebuilds its own markup, so the handlers have to be re-bound with it."""
    i = PORTAL_JS.index("function renderNotSent(")
    body = PORTAL_JS[i:PORTAL_JS.index("\n  /** The estimator picker", i)]
    assert "wireNotSentAssign(pid, row);" in body
