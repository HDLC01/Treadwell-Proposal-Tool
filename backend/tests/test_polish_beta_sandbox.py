"""The polish beta works on a TEST COPY of a project, never on the live bid.

WHAT HANZ ASKED FOR, IN HIS OWN WORDS.

2026-08-11: "I have a question for the polish estimate in beta does why is it when I click intake
and then proceed to estimate it doesnt lead me to the Estimate sheet in beta? instead it leads me
to the excel sheet still", and then the decision that this file protects:

    "The current polish excel sheet and the beta shuold be two different workflows okay? The BETA
     is for testing and which means all data from that leads to the 'test' Category of the
     proposals database"

Asked what should happen when somebody opens a REAL project in the beta, he chose "make a test
copy, leave the real bid alone", which is also his standing rule from 2026-08-07: never test
against a live Active project, file test work under the Test tab.

So Kyle opening Nearman Creek in the beta must leave Nearman Creek in Active, byte for byte, and
edit "Nearman Creek (beta test)" under Test. Pricing one job both ways and comparing the two is
the reason the beta runs beside the old screen instead of replacing it.

WHY SOURCE ASSERTIONS, FOR THIS FEATURE PARTICULARLY.

Four defects were found in this page in one day, every one of them by opening it in a browser and
every one of them green in CI first: it wiped Kyle's material rates on load, it froze 22 worksheet
formulas as constants, the fix for that deleted an estimator's own overrides, and the test-flag
POST went to a route that does not exist (the handler is api_test_flag_draft; the ROUTE is
"/test", and guessing from the name cost a silent 405 while the project sat in Active looking
fine). The failures this file covers are all of that shape (an ordering, an exact route, a
tri-state compared with the wrong operator), so they are checked in the source, and each test
names the mutation it exists to kill.
"""
import pathlib
import re

import pytest

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"

PAGE = "polish-estimate.js"


def _src(name: str) -> str:
    return (FRONTEND / "js" / name).read_text(encoding="utf-8")


def _code(name: str) -> str:
    """Source with // comment lines stripped.

    These files explain a bug by quoting it, so a raw grep matches its own prose. Same helper as
    test_no_blink_live_refresh.py, for the same reason.
    """
    return "\n".join(l for l in _src(name).splitlines() if not l.strip().startswith("//"))


def _block(name: str, fn: str) -> str:
    """The body of a top-level `function fn(...) {` in js/<name>.

    Brace-counted rather than regex'd so a nested literal cannot truncate the block and make an
    assertion vacuous. FUNCTION-SCOPED on purpose: a whole-file grep for one of these guard names
    would pass while the path that matters was broken.
    """
    src = _code(name)
    m = re.search(r"\n\s{2,6}(?:async\s+)?function " + re.escape(fn) + r"\s*\(", src)
    assert m, "%s() is gone from %s: these tests need rewriting, not deleting" % (fn, name)
    i = src.index("{", m.end())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    pytest.fail("unbalanced braces reading %s() in %s" % (fn, name))


def _catch_after(src: str, pos: int) -> str:
    """The body of the `catch` guarding the try that starts at/before `pos`, brace-counted.

    A fixed-size window is not enough, and that is not hypothetical: this file first read 600
    characters forward from each `await loadRow(`, and a `catch (e) { return true; }` on the
    SECOND read passed it, because the window ran on into the NEXT catch, which does stop the
    page. The mutation it let through is the beta editing the real bid whenever the copy read
    blips.
    """
    c = src.index("catch", pos)
    i = src.index("{", c)
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
        j += 1
    pytest.fail("unbalanced braces in the catch after offset %d" % pos)


@pytest.fixture()
def sandbox() -> str:
    return _block(PAGE, "enterSandbox")


# ── a live bid is copied, not edited ──────────────────────────────────────────
def test_a_project_that_is_not_filed_as_a_test_is_copied(sandbox):
    """The feature itself. Mutation: drop the copy and let the page open the project it was given.
    That is the bug being fixed, and on screen it looks like nothing at all."""
    assert "sandboxIdFor(id)" in sandbox, "no copy id is derived, so nothing is being copied"
    assert re.search(r"saveThenFileAsTest\(\s*copyId", sandbox), (
        "the copy is never written to the server")
    assert re.search(r"adoptDraft\(\s*copyId", sandbox), (
        "the page never switches onto the copy, so it is still editing the real bid")
    # REACHABILITY, not just presence. The first draft of this test asserted only that the copy
    # code was in the function, and a mutation that put `return true;` in front of the whole block
    # passed it: the copy sat there as dead code while the beta opened the live bid. So: between
    # the filed-as-test branch and the copy, nothing returns.
    direct_branch_end = sandbox.index("}", sandbox.index("return true", sandbox.index(
        "row.is_test === true")))
    gap = sandbox[direct_branch_end + 1:sandbox.index("sandboxIdFor(")]
    assert not re.search(r"\breturn\b", gap), (
        "something returns before the copy is made, so the copy path is dead code: %r" % gap)
    # And the gap alone was still not enough: `var copyId = sandboxIdFor(id); return true;` sits
    # AFTER the gap ends and left the copy just as dead. Past the filed-as-test branch there is
    # exactly one "carry on" left in this function, the one at the very end.
    tail = sandbox[direct_branch_end + 1:]
    assert tail.count("return true") == 1, (
        "a second 'return true' after the filed-as-test branch can short-circuit the copy: %r"
        % tail)


def test_a_project_already_filed_as_a_test_is_edited_directly(sandbox):
    """The normal path once somebody is working in the sandbox: no copy, no second suffix.

    Mutation: copy unconditionally, and every visit to a test project spawns another one."""
    direct = sandbox.index("row.is_test === true")
    first_copy = sandbox.index("sandboxIdFor(")
    assert direct < first_copy, "the copy id is derived before the filed-as-test check"
    branch = sandbox[direct:first_copy]
    assert "return true" in branch, "a project already filed as a test falls through to the copy"
    for forbidden in ("adoptDraft", "saveThenFileAsTest", "buildCopy"):
        assert forbidden not in branch, (
            "an already-filed test project still gets %s, so the sandbox copies itself" % forbidden)


def test_the_filed_as_test_check_is_exact_not_truthy(sandbox):
    """`is_test` is a TRI-STATE (see _tribool in backend/drafts.py): true = filed as a test,
    false = a human said "this IS a real bid", absent = nobody has said. Only `true` may skip the
    copy.

    Mutation: `if (row.is_test)`. Absent then reads as filed and the beta edits a live bid, the
    exact outcome this whole feature exists to prevent."""
    assert "row.is_test === true" in sandbox
    assert not re.search(r"if\s*\(\s*row\.is_test\s*[|)]", sandbox), (
        "the test filing is read as a truthy value, so an unfiled project would be edited in place")


# ── the source is read, never written ─────────────────────────────────────────
def test_the_real_project_is_only_ever_read():
    """loadRow is the one call that touches the live bid. A method or a body on it would make it
    able to change the thing it is protecting.

    Mutation: add `method: "PUT"` (or reuse this helper to save) and the guarantee is gone."""
    body = _block(PAGE, "loadRow")
    assert "fetch(" in body
    assert "method" not in body, "the source is fetched with a method, so it is not a read"
    assert "JSON.stringify" not in body, "the source fetch carries a body"


def test_only_the_copy_is_ever_written_to(sandbox):
    """The one write aimed at the page's OWN id is the never-saved case, where there is no source
    row in existence to protect. Once a source row is known to exist, nothing writes to it.

    Mutation: file the source as a test (its updated_at moves, it leaves Active, and Kyle's real
    bid is now a test project), or save the sandbox state under the source id."""
    own = sandbox.index("saveThenFileAsTest(id, state)")
    guard = sandbox.index("row === null")
    known_row = sandbox.index("row.is_test === true")
    assert guard < own < known_row, (
        "the page saves under the id it was given outside the never-saved branch")
    after = sandbox[known_row:]
    for forbidden in ("saveThenFileAsTest(id", "fileAsTest(id)", "adoptDraft(id"):
        assert forbidden not in after, (
            "%s writes to the real project after we know it exists" % forbidden)


def test_opening_the_beta_does_not_create_a_project(sandbox):
    """The sidebar door is a bare /polish-estimate.html with no ?d=, so shared.js has already
    MINTED an id by the time this runs (initDraftSync) and the `if (!id)` guard at the top can
    never fire. Saving unconditionally therefore filed a nameless row under the Test tab, `created`
    event and all, every time somebody opened the beta just to look at it. ae23c5d stopped the
    server doing this same thing ("the server stops creating projects nobody asked for").

    Mutation: save whatever the blob holds. Nothing on screen looks wrong, and the junk piles up in
    the Projects list where Kyle has to sort it out."""
    branch = sandbox[sandbox.index("row === null"):sandbox.index("row.is_test === true")]
    assert branch.index("hasContent(state)") < branch.index("saveThenFileAsTest(id, state)"), (
        "the never-saved branch writes a row before asking whether anything was typed into it")
    assert "markNewProjectAsTest(id)" in branch, (
        "an untouched project is never filed as a test at all, so the estimator's first real save "
        "in the beta would land in Active")


def test_the_deferred_filing_is_bound_to_this_project():
    """shared.js applies a pending intent after the first save that lands. Left unbound ("1"), it
    applies to whatever project is saved NEXT, which is how a real customer bid ends up filed as a
    test. That is the hazard bindNewProjectTestIntent was written for.

    Mutation: write the bare "1" that setNewProjectTestIntent writes."""
    body = _block(PAGE, "markNewProjectAsTest")
    assert "new_is_test" in body, "the intent is stored under a key shared.js does not read"
    assert 'id + ":1"' in body, "the pending test filing is not bound to this project's id"


def test_the_content_check_ignores_shared_js_s_own_stamp():
    """shared.js writes a stamped-EMPTY blob deliberately (its 404 floor, and again when the
    hydration loop guard trips), so `__draft_id` on its own is not work anybody did.

    Mutation: `Object.keys(blob).length > 0`, and a fresh visit creates a row again."""
    body = _block(PAGE, "hasContent")
    assert "__draft_id" in body, "shared.js's ownership stamp is counted as typed-in content"


def test_nothing_can_be_typed_in_before_the_sandbox_is_settled():
    """A save timer started against the real bid and fired after the switch would be this bug with
    extra steps, so the switch happens before the page is interactive at all.

    Mutation: move `await enterSandbox()` below the workbook load or the un-hide, and the first
    keystroke lands on the live project."""
    init = _block(PAGE, "init")
    sb = init.index("await enterSandbox()")
    assert init.index("TW.draftReady") < sb, (
        "the sandbox decides before shared.js has settled which draft the page is on")
    assert sb < init.index("/api/sheets"), "the workbook loads before the draft is settled"
    assert sb < init.index("pushCells();")
    assert sb < init.index('$("main").hidden = false'), (
        "the form is exposed to the estimator before the page knows which draft it may write to")


# ── the filing route, and its ordering ───────────────────────────────────────
def _polish_test_route() -> str:
    m = re.search(r'draftUrl\([^,]+,\s*"([^"]+)"\)', _block(PAGE, "fileAsTest"))
    assert m, "fileAsTest no longer builds its own URL; rewrite this test"
    return m.group(1)


def _projects_test_route() -> str:
    """Scoped to toggleTest, the Test? button on the Projects card. Reading the whole file finds
    /archive and /assign, which post to their own routes and would prove nothing."""
    m = re.search(r'"/api/draft/"\s*\+\s*encodeURIComponent\(id\)\s*\+\s*"([^"]+)"',
                  _block("projects.js", "toggleTest"))
    assert m, "projects.js no longer posts the test flag; rewrite this test"
    return m.group(1)


def test_the_copy_is_filed_through_the_same_route_projects_js_uses():
    """The route is "/test". Naming it after the handler (api_test_flag_draft) POSTs to a route
    that does not exist, answers 405, and leaves the project in Active looking completely normal,
    which is what happened earlier today, and source tests that only checked a string was present
    could not see it. Pinned against the Test? button on the Projects card so the two cannot
    drift apart."""
    mine = _polish_test_route()
    theirs = _projects_test_route()
    assert mine == theirs == "/test", "polish beta posts %r, projects.js posts %r" % (mine, theirs)
    assert "/test-flag" not in _code(PAGE), "the flag is posted to a route that does not exist"
    body = _block(PAGE, "fileAsTest")
    assert '"POST"' in body and "is_test" in body


def test_the_test_flag_is_only_set_after_a_save_that_landed():
    """set_test_flag returns False on a missing draft, so filing before the first successful save
    is a silent no-op and the copy stays in Active.

    And "landed" is not res.ok: api_save_draft catches its own failures and answers 200 with
    {"ok": false, "error": ...}.

    Mutations: file before the PUT; or trust res.ok alone."""
    body = _block(PAGE, "saveThenFileAsTest")
    put = body.index('method: "PUT"')
    thrown = body.index("throw new Error")
    flag = body.index("fileAsTest(")
    assert put < thrown < flag, "the test flag is set before the save is known to have worked"
    assert "res.ok" in body
    assert "body.ok === false" in body, (
        'a 200 carrying {"ok": false} is being read as a successful save')
    assert re.search(r"await fileAsTest\(", body), "the filing is not awaited"


def test_the_writes_survive_a_navigation():
    """The estimator can click away mid-copy; a plain fetch is cancelled on unload, which is why
    shared.js carries its own saves this way."""
    for fn in ("saveThenFileAsTest", "fileAsTest"):
        assert "keepalive: true" in _block(PAGE, fn), "%s can be cancelled by a navigation" % fn


# ── the page, and the URL, move onto the copy ────────────────────────────────
def test_the_draft_id_and_the_url_both_move_to_the_copy():
    """A reload that still said ?d=<the real project> would land back on the live bid and the next
    autosave would write to it.

    Mutation: keep the id in memory only and leave the address bar alone."""
    body = _block(PAGE, "adoptDraft")
    assert 'searchParams.set("d", id)' in body and "history.replaceState" in body, (
        "the address bar still names the project the estimator came from")
    assert 'localStorage.setItem("treadwell.proposal_tool.draft_id", id)' in body, (
        "shared.js's stored draft id still points at the source, so a navigation that drops the "
        "query string goes back to it")


def test_the_identity_moves_before_the_first_save():
    """setState pushes to whatever draft the page currently claims to be, so the clear + the id
    move both have to happen first. Mutation: save first, and the copy's blob is PUT straight over
    the real bid."""
    body = _block(PAGE, "adoptDraft")
    save = body.index("TW.setState(")
    assert body.index("TW.clearState()") < save, (
        "the source's stamped blob is still in localStorage when the write is scheduled")
    assert body.index('searchParams.set("d", id)') < save
    assert body.index('localStorage.setItem("treadwell.proposal_tool.draft_id", id)') < save


def test_the_wizard_links_follow_the_copy():
    """shared.js stamps ?d= onto the static step links at DOMContentLoaded, long before this page
    has settled its draft. Left alone, "3 · Proposal" walks the estimator back onto the real bid.

    Mutation: drop the repoint, and every link out of the beta leaves the sandbox."""
    assert "repointWizardLinks()" in _block(PAGE, "adoptDraft")
    body = _block(PAGE, "repointWizardLinks")
    assert "TW.getDraftId()" in body and 'searchParams.set("d", id)' in body
    shell = _block(PAGE, "shell")
    assert 'TW.withDraft("/proposal-review.html")' in shell, (
        "the Continue button is a bare path, so it relies on whatever draft id happens to be "
        "stored rather than the one being edited")


# ── reopening does not mint a second copy ────────────────────────────────────
def test_the_copy_id_is_derived_so_reopening_finds_the_same_copy(sandbox):
    """Mutation: mint a fresh id. Then opening Nearman Creek in the beta four times leaves four
    "Nearman Creek (beta test)" rows and no way to tell which one holds the numbers."""
    code = _code(PAGE)
    for minted in ("randomUUID", "newDraftId"):
        assert minted not in code, (
            "the sandbox id is minted (%s), so every visit makes another copy" % minted)
    assert "id +" in _block(PAGE, "sandboxIdFor"), "the copy id is not derived from the source's"
    assert re.search(r"copy\s*=\s*await loadRow\(\s*copyId\s*\)", sandbox), (
        "the existing copy is never looked for")
    assert re.search(r"if\s*\(\s*copy\s*\)", sandbox), "a copy that exists is not reused"


def test_an_existing_copy_is_not_reseeded_from_the_source(sandbox):
    """The second visit is where the comparison lives: the copy holds what was priced here last
    time. Mutation: rebuild it from the source, and the estimator's sandbox work is silently
    replaced by the real bid's numbers."""
    i = sandbox.index("if (copy) {")
    j = sandbox.index("} else {", i)
    branch = sandbox[i:j]
    assert "adoptDraft(copyId, copy)" in branch, "the existing copy is not what gets adopted"
    for forbidden in ("buildCopy", "saveThenFileAsTest"):
        assert forbidden not in branch, (
            "reopening %s over the existing copy" % forbidden)


def test_the_beta_suffix_does_not_accumulate():
    """Mutation: append unconditionally, and a copy of a copy reads "X (beta test) (beta test)"."""
    body = _block(PAGE, "betaName")
    assert "slice(-BETA_SUFFIX.length)" in body, (
        "the name is not checked for the suffix it is about to be given")
    assert body.count("BETA_SUFFIX") >= 2, "the suffix is appended without ever being compared"


def test_the_copy_does_not_carry_the_keys_the_server_owns():
    """is_test above all. A source that a human filed as a real bid carries `false`, this page PUTs
    the whole blob on every autosave, and _SERVER_OWNED_KEYS only stops the server's value being
    dropped, not replaced. So the copy would be filed as a test through /test and then quietly
    returned to Active seconds later.

    Mutation: `Object.assign({}, srcData)` and nothing else."""
    body = _block(PAGE, "buildCopy")
    for key in ("is_test", "archived", "assigned_estimator", "__draft_id"):
        assert "delete blob." + key in body, "the copy inherits the source's %s" % key
    assert "blob.beta_sandbox_of = srcId" in body, (
        "the copy does not say whose sandbox it is, so nothing but its id identifies it")
    assert "betaName(" in body, "the copy keeps the real project's name"


def test_a_copy_names_its_source_so_it_is_never_copied_again(sandbox):
    """Belt and braces with the derived id: if the /test POST ever fails, the copy is a project
    that is NOT filed as a test, and without this it would be copied in turn.

    Mutation: check only is_test."""
    assert "row.beta_sandbox_of" in sandbox, (
        "a sandbox copy whose test flag never landed would be copied again")


# ── the estimator is told ─────────────────────────────────────────────────────
def test_the_notice_names_the_source_and_says_it_is_untouched(sandbox):
    """Silently working on a different project than the one clicked is worse than the bug being
    fixed. Mutation: switch drafts quietly."""
    html = (FRONTEND / "polish-estimate.html").read_text(encoding="utf-8")
    assert 'id="sandbox-note"' in html, "there is nowhere on the page for the notice to render"
    assert re.search(r"showCopyNote\(\s*row\.project_name", sandbox), (
        "the notice does not name the project that was opened")
    body = _block(PAGE, "showCopyNote")
    assert "srcName" in body and "copyName" in body, "the notice names only one of the two projects"
    assert "untouched" in body, "the notice never says the real project is left alone"
    assert "hidden = false" in body, "the notice is built but never shown"


def test_the_notice_cannot_be_markup():
    """Project names are typed by estimators and read back by everyone. This one is built from a
    project name on every code path, so it is text nodes only."""
    for fn in ("showCopyNote", "showDirectNote"):
        body = _block(PAGE, fn)
        assert "innerHTML" not in body, "%s builds a project name into markup" % fn
        assert "textContent" in body or "createTextNode" in body


def test_an_indeterminate_answer_stops_the_page_instead_of_guessing(sandbox):
    """A blip on either read must not be resolved as "not a test" (a needless copy) or as "filed"
    (editing a live bid). The page stops on its loading message and says why.

    Mutation: `catch { return true; }`, which is a beta that edits a customer's bid whenever a
    fetch fails."""
    reads = [m.end() for m in re.finditer(r"await loadRow\(", sandbox)]
    assert len(reads) == 2, "expected the source read and the copy read; found %d" % len(reads)
    for n, pos in enumerate(reads, 1):
        body = _catch_after(sandbox, pos)
        assert "return false" in body, (
            "read %d carries on after a failed fetch instead of stopping the page: %r" % (n, body))
        assert "loading" in body, (
            "read %d stops with no reason on screen: %r" % (n, body))
