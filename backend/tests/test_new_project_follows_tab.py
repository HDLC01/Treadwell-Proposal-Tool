"""+ New project lands in the tab it was started from.

WHAT THIS IS FOR.

Pressing "+ New project" while standing in the Test tab reads as "make me a test project", and
it used to make a live one. You then had to return to Projects and press Test? on the card — or
forget, and leave a test sitting in Kyle's working list among real customer bids. Hanz,
2026-08-07: "It should land in test... If its active it should land in active."

THE DESIGN CHANGED ON 2026-10-21 (X1, round 2), AND THIS FILE CHANGED WITH IT. The start used to be applied by a POST
/test after the project's first save came back, and "kept out of the blob" was the rule that made that necessary: a tab
holding its own is_test would overwrite whatever somebody had since chosen on the card. A POST needs a page that is
still there to see the first save come back, and every way of leaving that did not wait (a link, Back, a closed tab, a
double press) left the project BORN UNFILED on the board where staff work. Now shared.js's setState says the start in the
project's OWN blob, on the first write that has anything in it, so the first PUT creates the row already filed; and
`drafts.save_draft(keep_server_owned=True)` is what makes that safe, because the stored value of a server-owned key wins
over a blob's whenever the row has one. test_v2_new_estimate_test_flag.py EXECUTES all of it (the real shared.js, the real
click handler of projects.js and the real routes); this file keeps the cheap source-level pins of the wiring.

THE THREE WAYS THIS GOES WRONG, WHICH IS WHAT THESE TESTS GUARD.

1. **The flag overruling somebody.** A blob that already says is_test (a hydrate wrote what the server holds) is never
   overwritten by a start, and the server keeps a stored value over any blob. File a project as real, leave yesterday's tab
   open, and its next autosave must not file it back as a test.

2. **The intent left unbound.** It would attach to whichever project was written next — press New project, change your
   mind, open a real customer bid, and that bid gets filed as a test.

3. **A second request.** A /test after the save is what failed (a page that had left, a failure nobody read, an answer
   nobody waited for). Nothing in shared.js files a project with a request of its own any more.

Source-level, like the other frontend guards in this suite: what is checkable here is that the wiring is present and
shaped correctly.
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


def _exact(code, name):
    """`function name(...) { ... }` and nothing after it: brace-counted, because _body runs on to the next plain `function`
    and an `async function` in between (shared.js has several) would be swept in with it."""
    i = code.index("function " + name)
    j = code.index("{", code.index(")", i))
    depth = 0
    for k in range(j, len(code)):
        depth += {"{": 1, "}": -1}.get(code[k], 0)
        if depth == 0:
            return code[i:k + 1]
    raise AssertionError("unbalanced braces in " + name)


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


def test_the_flag_goes_into_the_blob_only_as_a_new_projects_own_first_write(shared):
    """The rule this file used to hold the other way round. The intent lives under its own localStorage key; setState is what
    says it in the project's blob (and nothing else writes it there on this browser's own authority); and putDraft never
    adds is_test to what it sends, so a blob that does not say it (a project somebody has since filed) is not re-flagged from
    there. The executed counterparts are in test_v2_new_estimate_test_flag.py (the first PUT carries it; a stale tab cannot
    undo a human's filing, against the real routes)."""
    assert "treadwell.proposal_tool.new_is_test" in shared
    set_state = _body(shared, "setState")
    assert "sayWhatItWasStartedAs(id, merged)" in set_state, "setState does not say what the project was started as"
    assert "sayWhatItWasStartedAs" not in _body(shared, "setLocalState"), (
        "setLocalState is for facts the server holds already: it must not start saying one of its own")
    put = _body(shared, "putDraft")
    assert "is_test" not in put, "putDraft adds is_test to the blob it sends, which re-flags a project somebody filed since"


def test_nothing_in_shared_js_files_a_project_with_a_request_of_its_own(shared):
    """A /test after the save is what failed: it needs a page that is still there to see the save come back, its failure was
    never read, and a page booting on it waited for ever. The start travels in the first save, so shared.js has no route of
    its own to file with (the Test? button on the Projects card still has one, and the sandbox's refile of a copy)."""
    assert "applyPendingTestIntent" not in shared, "the second request is back"
    assert not re.search(r'"/api/draft/"\s*\+\s*encodeURIComponent\(\w+\)\s*\+\s*"/test"', shared), (
        "shared.js posts to /test again")
    stamp = _exact(shared, "sayWhatItWasStartedAs")
    assert "fetch(" not in stamp and "keepalive" not in stamp, "the stamp makes a request"
    projects_src = PROJECTS.read_text(encoding="utf-8")
    assert re.search(r'"/api/draft/"\s*\+\s*encodeURIComponent\(\w+\)\s*\+\s*"/test"', projects_src), (
        "projects.js no longer posts to /test: the Test? button has moved, and this file's reference point with it")


def test_the_intent_is_bound_to_an_id_before_it_can_be_used(shared):
    """Unbound, it would land on whichever project was written next."""
    assert "bindNewProjectTestIntent" in shared
    stamp = _exact(shared, "sayWhatItWasStartedAs")
    assert "pendingTestIntentFor(id)" in stamp
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


def test_the_start_is_used_up_by_the_write_that_says_it(shared):
    """One shot. A start left in the one localStorage slot after it has been said would wait there for a stranger (the next
    new project overwrites the slot, a project that has moved on would be filed by it). It is emptied by the first write that
    holds anything, before the blob is touched, and not by a write that holds nothing."""
    body = _exact(shared, "sayWhatItWasStartedAs")
    assert "removeItem" in body
    content_check = body.index("k !== STAMP")
    assert content_check < body.index("removeItem") < body.index("blob.is_test = want"), (
        "the start is not checked for content first, or not used up before it is said")
    assert 'hasOwnProperty.call(blob, "is_test")' in body, (
        "a blob that already says is_test is overwritten by a start (a human's word, or the server's, would lose)")


def test_shared_exports_the_setter_projects_calls(shared):
    """projects.js calls TW.setNewProjectTestIntent; an unexported function is a runtime
    TypeError inside a try/catch, so the tab would be ignored silently."""
    i = shared.index("window.TW = {")
    assert "setNewProjectTestIntent" in shared[i:]
