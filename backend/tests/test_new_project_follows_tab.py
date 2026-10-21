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

AND IT CHANGED AGAIN IN ROUND 3. The start had been ONE localStorage slot for the whole browser ("<id>:<0|1>", bound to the id
when shared.js minted it), and the audit found it overwritten by a page that only LOOKED at a project (a v2 page, F1) and by a
second tab's New project (F3), and unreachable for a blob that never went through setState (F2). Now each project's start is
its OWN key (NEW_IS_TEST_KEY + ":" + id), minted together with the project's id by setNewProjectTestIntent as New project is
pressed, so the id never has to be bound later and no other project's start can be read as this one's; a v2 page's own word
("this page created the project") is held in that page's memory (startsAsTest) and goes into the first write that page makes;
and putDraft puts the start on a copy that never went through setState (withStart).

THE WAYS THIS GOES WRONG, WHICH IS WHAT THESE TESTS GUARD.

1. **The flag overruling somebody.** A blob that already says is_test (a hydrate wrote what the server holds) is never
   overwritten by a start, and the server keeps a stored value over any blob. File a project as real, leave yesterday's tab
   open, and its next autosave must not file it back as a test.

2. **The start read as another project's.** Press New project, change your mind, open a real customer bid, and that bid
   must not be filed as a test: a start is under its own project's key and can only ever be read by that project.

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
    """The rule this file used to hold the other way round. The start lives under its own localStorage key; setState is what
    says it in the project's blob (and nothing else writes it there on this browser's own authority); and putDraft adds
    is_test to a COPY it sends only through withStart, which does it from a start this browser holds for that very id and
    never over a word the blob already has, so a project somebody has since filed is not re-flagged from there. The executed
    counterparts are in test_v2_new_estimate_test_flag.py (the first PUT carries it; a stale tab cannot undo a human's
    filing, against the real routes)."""
    assert "treadwell.proposal_tool.new_is_test" in shared
    set_state = _body(shared, "setState")
    assert "sayWhatItWasStartedAs(id, merged)" in set_state, "setState does not say what the project was started as"
    assert "sayWhatItWasStartedAs" not in _body(shared, "setLocalState"), (
        "setLocalState is for facts the server holds already: it must not start saying one of its own")
    put = _body(shared, "putDraft")
    assert "is_test" not in put, "putDraft adds is_test to the blob it sends, which re-flags a project somebody filed since"
    assert "withStart(id, blob)" in put, "putDraft does not put a start on a copy that never went through setState"
    with_start = _exact(shared, "withStart")
    assert 'hasOwnProperty.call(blob, "is_test")) return blob' in with_start, "withStart overrules a word the blob already holds"
    assert "startOf(id)" in with_start and "Object.assign({}, blob," in with_start, "withStart changes the caller's blob or reads another key"


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


def test_a_start_is_under_its_own_projects_key(shared):
    """One key per project, so no other project's start (or another tab's) can be read as this one's: the key carries the id, the
    stamp and putDraft read only that key, and New project writes it for the id it has just minted."""
    assert 'function startKey(id) { return NEW_IS_TEST_KEY + ":" + id; }' in shared
    assert "startKey(id)" in _exact(shared, "startOf"), "the start is read from a key that is not the project's own"
    stamp = _exact(shared, "sayWhatItWasStartedAs")
    assert "startOf(id)" in stamp and "startKey(id)" in stamp
    setter = _exact(shared, "setNewProjectTestIntent")
    assert "newDraftId()" in setter and "DRAFT_ID_KEY" in setter and "startKey(id)" in setter, (
        "New project does not leave the project's id and its own start together")


def test_arriving_at_an_existing_project_has_no_start_to_drop(shared):
    """Press New project, change your mind, open a real customer bid: that bid must not be filed as a test. It cannot be: the
    abandoned project's start is under that project's own key, and initDraftSync neither reads nor drops one (it used to drop
    the one global slot here, and to bind it when it minted an id)."""
    assert "dropUnboundTestIntent" not in shared and "bindNewProjectTestIntent" not in shared
    init = _body(shared, "initDraftSync")
    assert "NEW_IS_TEST_KEY" not in init and "startOf(" not in init and "minting" not in init


def test_new_project_mints_an_id_only_for_a_position(shared):
    """A position (the Test tab, the Active tab) mints the project's id with its start. All and Inactive say nothing, so there
    is nothing to keep and the page that opens mints the project as it always did."""
    setter = _exact(shared, "setNewProjectTestIntent")
    assert re.search(r"if \(want === null \|\| want === undefined\) return;", setter), setter
    assert setter.index("want === null") < setter.index("newDraftId()"), "All and Inactive mint an id"


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
