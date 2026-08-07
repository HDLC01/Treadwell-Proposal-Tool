"""+ New project lands in the tab it was started from.

WHAT THIS IS FOR.

Pressing "+ New project" while standing in the Test tab reads as "make me a test project", and
it used to make a live one. You then had to return to Projects and press Test? on the card — or
forget, and leave a test sitting in Kyle's working list among real customer bids. Hanz,
2026-08-07: "It should land in test... If its active it should land in active."

THE THREE WAYS THIS GOES WRONG, WHICH IS WHAT THESE TESTS GUARD.

1. **The flag written into the saved blob.** `is_test` is server-owned (`_SERVER_OWNED_KEYS` in
   drafts.py) precisely because the browser PUTs the whole blob on every autosave. A tab holding
   its own copy would overwrite whatever somebody had since chosen on the card: file a project
   as real, leave yesterday's tab open, and its next autosave files it back as a test. So the
   intent must travel outside the blob and be applied through /test-flag.

2. **The intent left unbound.** It would attach to whichever project was saved next — press New
   project, change your mind, open a real customer bid, and that bid gets filed as a test.

3. **Applied before the project exists.** `set_test_flag` returns False on a missing draft, so
   filing before the first save is a silent no-op and the project stays in Active looking as
   though it worked.

Source-level, like the other frontend guards in this suite: the behaviour lives in a browser
page, and what is checkable here is that the wiring is present and shaped correctly.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
SHARED = FRONTEND / "shared.js"
PROJECTS = FRONTEND / "js" / "projects.js"


def _code(path):
    """Source with // comments stripped.

    The comments here explain the failure modes by describing them, so a raw grep matches its own
    prose. That has caught me out repeatedly in this repo.
    """
    return "\n".join(l for l in path.read_text(encoding="utf-8").splitlines()
                     if not l.strip().startswith("//"))


def _body(code, name):
    i = code.index("function " + name)
    j = code.find("\n  function ", i + 1)
    return code[i:j if j != -1 else len(code)]


@pytest.fixture(scope="module")
def shared():
    return _code(SHARED)


@pytest.fixture(scope="module")
def projects():
    return _code(PROJECTS)


def test_projects_records_the_tab_when_new_project_is_pressed(projects):
    i = projects.index('getElementById("new-project")')
    block = projects[i:i + 1400]
    assert "CURRENT_FILTER" in block, "the handler ignores which tab you are standing in"
    assert "setNewProjectTestIntent" in block


def test_test_tab_files_as_test_and_active_files_as_real(projects):
    i = projects.index('getElementById("new-project")')
    block = projects[i:i + 1400]
    assert re.search(r'CURRENT_FILTER\s*===\s*"test"\s*\)\s*TW\.setNewProjectTestIntent\(true\)',
                     block), "starting from Test does not produce a test project"
    assert re.search(r'CURRENT_FILTER\s*===\s*"active"\s*\)\s*TW\.setNewProjectTestIntent\(false\)',
                     block), (
        "starting from Active must write FALSE, not nothing — absent lets the name heuristic "
        "vote, so a real bid for a customer with 'test' in its name files itself away")


def test_all_and_inactive_state_no_opinion(projects):
    """Neither tab is a statement about test-ness, so neither should force one."""
    i = projects.index('getElementById("new-project")')
    block = projects[i:i + 1400]
    assert "setNewProjectTestIntent(null)" in block


def test_the_flag_never_goes_into_the_saved_blob(shared):
    """The reason this whole mechanism exists rather than a field on the state object.

    A tab holding its own `is_test` overwrites whatever somebody has since chosen on the card,
    because every autosave PUTs the whole blob.
    """
    assert "setState" in shared
    # The intent lives under its own localStorage key, not in the draft state.
    assert "treadwell.proposal_tool.new_is_test" in shared
    # It must not be smuggled into the PUT body.
    put = _body(shared, "putDraft")
    assert "is_test" not in put, (
        "putDraft sends is_test in the blob, which lets a stale tab undo somebody's filing")


def test_it_posts_to_the_same_endpoint_the_Test_button_uses():
    """The route, not a plausible-looking spelling of it.

    An earlier version guessed "/test-flag" from the handler name `api_test_flag_draft`. The
    real route is "/test". Every call 405'd and the project silently stayed in Active — and the
    test passed, because it only asserted the string "test-flag" appeared in the file.

    Comparing against projects.js is what makes this bite: both call the same endpoint, so if
    one is wrong they disagree, and if the route is ever renamed both have to move together.
    """
    shared_src = SHARED.read_text(encoding="utf-8")
    projects_src = PROJECTS.read_text(encoding="utf-8")
    pat = r'"/api/draft/"\s*\+\s*encodeURIComponent\(\w+\)\s*\+\s*"(/[a-z-]+)"'
    theirs = set(re.findall(pat, projects_src))
    mine = set(re.findall(pat, shared_src))
    assert "/test" in theirs, (
        "projects.js no longer posts to /test; this test's reference point has moved: %s" % theirs)
    assert "/test" in mine, (
        "shared.js files the new project at %s, but the Test? button uses /test" % (mine or "nothing"))


def test_the_call_survives_the_navigation_that_usually_follows_it():
    """Intake submits and goes straight to Estimate Review, so the first save and the page
    unload happen together. Without keepalive the browser cancels the flag POST in flight — the
    PUT beside it carries keepalive for exactly this reason."""
    shared_src = SHARED.read_text(encoding="utf-8")
    i = shared_src.index("function applyPendingTestIntent")
    body = shared_src[i:i + 1400]
    assert "keepalive: true" in body, (
        "the flag POST is cancelled when intake navigates to Estimate Review")


def test_the_intent_is_bound_to_an_id_before_it_can_be_applied(shared):
    """Unbound, it would land on whichever project was saved next."""
    assert "bindNewProjectTestIntent" in shared
    apply_body = _body(shared, "applyPendingTestIntent")
    assert "pendingTestIntentFor" in apply_body
    match = _body(shared, "pendingTestIntentFor")
    assert "raw.slice(0, i) !== id" in match, (
        "the pending intent is not checked against the draft it was meant for")


def test_an_abandoned_intent_is_dropped_when_an_existing_project_is_opened(shared):
    """Press New project, change your mind, open a real customer bid: that bid must not be
    filed as a test."""
    assert "dropUnboundTestIntent" in shared
    init = _body(shared, "initDraftSync")
    assert "dropUnboundTestIntent()" in init


def test_the_intent_is_only_bound_when_a_NEW_id_is_minted(shared):
    """Resuming a project the browser already had an id for is not a new project, and binding
    there would file whatever the estimator last worked on."""
    init = _body(shared, "initDraftSync")
    assert "minting" in init and "!localId" in init
    assert re.search(r'if\s*\(minting\)\s*bindNewProjectTestIntent', init)


def test_the_flag_is_applied_only_after_the_project_reaches_the_server(shared):
    """set_test_flag returns False on a missing draft, so filing before the first save is a
    silent no-op — the project stays in Active looking as though it worked."""
    put = _body(shared, "putDraft")
    assert "res.ok" in put and "applyPendingTestIntent" in put, (
        "the flag is applied without waiting for the save to succeed")


def test_the_intent_is_cleared_once_so_it_cannot_fight_a_later_decision(shared):
    """A retry that outlived the page would re-file a project the estimator had since moved."""
    body = _body(shared, "applyPendingTestIntent")
    assert "removeItem" in body
    assert body.index("removeItem") < body.index("fetch("), (
        "the intent is cleared only on success, so a failure leaves it armed for the next save")


def test_shared_exports_the_setter_projects_calls(shared):
    """projects.js calls TW.setNewProjectTestIntent; an unexported function is a runtime
    TypeError inside a try/catch, so the tab would be ignored silently."""
    i = shared.index("window.TW = {")
    assert "setNewProjectTestIntent" in shared[i:]
