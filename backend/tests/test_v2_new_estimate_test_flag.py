"""X1 -- A NEW v2 ESTIMATE IS FILED UNDER TEST, HOWEVER FAST THE ESTIMATOR LEAVES THE INTAKE (2026-10-21).

THE DEFECT, walked on staging 59922bd. "New estimate" on the v2 board opens the v2 intake for a NEW project, and the
intake says it is "saved as a NEW test project, under the Test tab". The promise is an intent that shared.js applies
the moment the project's first PUT comes back stored (the server has no row to file before that). Press Continue
within about three seconds of the last edit and no page is there to see that reply: onSubmit saved and left in the
same breath, so the first PUT went out through the pagehide handler (keepalive) and its reply was lost. The row was
created and never filed, it sat on the Direct Projects board where staff work, and the estimate page then forked a
"(beta test)" copy of it ("You are editing a test copy ... The real project ... is untouched in Active"). Two of two
fast flows did this and three of three slow ones (a pause of three seconds or more, or anything that lets the 2.5 s
autosave PUT land on the live page) filed correctly.

THE FIX, in two layers.
  T1  Continue waits for the save, on the page the estimator is still on (js/polish-intake.js onSubmit), and the
      save's promise now includes the filing that follows it (shared.js putDraft), so the first PUT and the POST
      that files the project are both answered to a live page before the browser leaves, whatever each takes.
  T2  The estimate page's sandbox (js/polish-sandbox.js enterSandbox) files a project that this browser made as a
      new test project and finds still unfiled, instead of forking it: the net under every other way of leaving
      the intake (a step link, the tab closing, a reload) that sends the first PUT as the page goes.

HOW THESE TESTS RUN. tests/js/new-estimate-test-flag-harness.js runs the REAL shared.js, js/polish-sandbox.js and
js/polish-intake.js, whole, in tests/js/_world.js: a browser model with virtual time in which a page's timers and
replies die with it and a keepalive request survives it with nobody to hear the answer. The intake is driven as a
person drives it (the board's New estimate, typing, Continue); every fact is read off the server's rows and the
pages after everything has settled. The model reproduces X1 on 59922bd (see the first test of each flow), and the
MUTATION tests at the end break a COPY of each source one line at a time and require a named check to go red.
"""
import pathlib
import re

import pytest

import drafts
from _golden_support import FRONTEND
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
HARNESS = TESTS / "js" / "new-estimate-test-flag-harness.js"
# What the harness reads from a frontend directory (a scratch copy for the mutation runs must hold all of it).
PAGE_FILES = ["shared.js", "polish-intake.html", "js/polish-intake.js", "js/polish-sandbox.js", "js/work-types.js",
              "js/intake-scope.js", "js/bid-model.js", "js/excel-math.js"]
INTENT_KEY = "treadwell.proposal_tool.new_is_test"
DIRECT = "editing it directly"            # showDirectNote(false): "... Estimating Tool v2 is editing it directly."
COPY = "test copy"                        # showCopyNote: "You are editing a test copy. ..."


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend, timeout=600)
    assert proc.returncode == 0, "the harness itself failed. Read this before assuming a product bug:\n" + proc.stderr[-1500:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    return run()


# ── reading a run ────────────────────────────────────────────────────────────────────────────────────────
def reqs(r, route=None, id_=None, page=None):
    """The requests of a run, oldest first, narrowed to a route, a draft id and the kind of page that sent them."""
    return [q for q in r["requests"]
            if (route is None or q["route"] == route) and (id_ is None or q["id"] == id_)
            and (page is None or q["page"].startswith(page))]


def says(r):
    return (r["estimate"] or {}).get("note", "")


def describe(r):
    """A run in one line, for a failure message: the project, its copy, the intent, and what the estimate page said."""
    e = r["estimate"] or {}
    return "project %s, beta copy %s, intent %r, estimate page on %s said %r" % (
        r["x"], r["beta"], r["intent"], e.get("draftId"), says(r)[:90])


def assert_filed_and_edited_directly(r, flow):
    """THE PROMISE: the project the estimator started is filed under Test (is_test true), the intent that
    carried it is used up, no beta copy exists, and the estimate page is on that very project and says it is
    editing a test project directly."""
    est = r["estimate"] or {}
    assert r["x"] is not None and r["x"]["is_test"] is True, "%s: the new project was not filed under Test: %s" % (flow, describe(r))
    assert r["beta"] is None and r["rowIds"] == [r["id"]], "%s: a beta copy was forked: %s" % (flow, describe(r))
    assert r["intent"] is None, "%s: the intent was not used up (%r)" % (flow, r["intent"])
    assert est.get("settled") is True and est.get("draftId") == r["id"], "%s: the estimate page is not on the project: %s" % (flow, describe(r))
    assert DIRECT in says(r) and COPY not in says(r), "%s: the estimate page does not say it is editing the test project directly: %s" % (flow, describe(r))


# ══ the model ════════════════════════════════════════════════════════════════════════════════════════════
def test_the_model_is_a_browser_that_drops_what_a_browser_drops(ran):
    """If the model were kinder than a browser, X1 could not be reproduced here; if it were harsher, the fix could
    be right for the wrong reason. So it is held to what a browser does with a page it is leaving: the old page
    keeps running until the new document commits (a reply that comes back in that time is SEEN), a request that
    had reached the server is finished whatever happens to the page, a reply to a page that has gone is seen by
    nobody, a keepalive request sent as the page goes survives it and a plain one does not, and a timer of a page
    that has gone never fires."""
    m = ran["model"]
    assert (m["earlyStored"], m["earlyReplySeen"], m["earlyOutcome"]) == (True, True, "replied")
    assert (m["lateStored"], m["lateReplySeen"], m["lateOutcome"]) == (True, False, "reply dropped")
    assert (m["keepaliveStored"], m["keepaliveReplySeen"], m["keepaliveOutcome"]) == (True, False, "reply dropped")
    assert (m["plainStored"], m["plainReplySeen"], m["plainOutcome"]) == (False, False, "aborted")
    assert m["timerOfAGonePageFired"] is False
    assert m["pageDiedAt"] == m["commitMs"], "the old page does not run until the new document commits"


def test_the_server_model_is_the_route_contract_of_the_backend(ran):
    """The three behaviours the fix leans on, as backend/main.py and backend/drafts.py have them: a save keeps the
    server-owned keys (so a page can never file a project by sending is_test), and filing a project that has no
    row answers 200 with {"ok": true, "existed": false} (so a filing that did nothing can be told from one that
    worked)."""
    m = ran["model"]
    assert m["serverOwnedKeys"] == list(drafts._SERVER_OWNED_KEYS)
    assert m["savingKeepsServerOwnedKeys"] == {"is_test": True, "archived": False, "assigned_estimator": "kyle@x.test",
                                               "project_name": "B"}
    assert m["fileMissingRow"] == {"ok": True, "existed": False, "is_test": True}


def test_the_board_opens_the_intake_the_way_the_harness_does():
    """The harness does what js/v2-board.js startNew() does before the intake opens: clear the three keys that
    make shared.js mint a fresh draft, then open /polish-intake.html with no ?d=. Read from the board's source so
    the harness cannot keep walking a flow the board no longer starts."""
    src = (FRONTEND / "js" / "v2-board.js").read_text(encoding="utf-8")
    body = src[src.index("function startNew()"):]
    body = body[:body.index("\n  }\n")]
    cleared = re.findall(r'(?:local|session)Storage\.removeItem\("([^"]+)"\)', body)
    assert sorted(cleared) == sorted(["treadwell.proposal_tool.state", "treadwell.proposal_tool.draft_id",
                                      "treadwell.proposal_tool.hydrated_once"]), cleared
    assert 'window.location.assign("/polish-intake.html")' in body, "the board no longer sends the browser to a bare intake"


def test_the_estimate_page_the_harness_runs_is_the_real_ones_first_lines():
    """The harness's estimate page is the first lines of polish-estimate.js init(): shared.js settles the draft,
    the page adopts what is stored, then the sandbox decides which draft the page may write to. The real file is
    5,000 lines of calculator; the part that forks a project is this call, so the order is held here."""
    src = (FRONTEND / "js" / "polish-estimate.js").read_text(encoding="utf-8")
    body = src[src.index("async function init()"):]
    body = body[:body.index("var savedEstimate")]
    order = [body.index(s) for s in ("await TW.draftReady", "adopt(TW.getState())", "await S.enterSandbox(adopt)")]
    assert order == sorted(order), "polish-estimate.js init() no longer runs these in this order: %r" % order


# ══ T1: a fast Continue files the project ═══════════════════════════════════════════════════════════════
@pytest.mark.parametrize("flow", ["fast", "fastAfterAutosave"])
def test_a_fast_continue_files_the_new_project_under_test(ran, flow):
    """THE DEFECT. Continue 100 ms after the last edit (nothing has been saved), and at 700 ms (the 600 ms autosave
    has run and the 2.5 s timer that sends it is armed): the project is filed under Test, nothing is forked, the
    intent is used up and the estimate page says it is editing the test project directly.

    Red on 59922bd: the project sits unfiled, est-1-beta exists, and the estimate page says "You are editing a
    test copy ... The real project ... is untouched in Active"."""
    assert_filed_and_edited_directly(ran[flow], flow)


def test_the_first_save_and_its_filing_are_answered_to_a_page_that_is_still_there(ran):
    """WHY it works, not only that it does. The first PUT is a plain request whose reply the intake page sees, the
    filing is sent after it from that same page and answered to it, and Continue leaves only after that.

    Red on 59922bd: the first PUT is the pagehide keepalive one, its reply is dropped, and nothing is ever filed."""
    r = ran["fast"]
    puts = reqs(r, "PUT", r["id"])
    assert puts and puts[0]["page"].startswith("intake"), puts
    assert (puts[0]["keepalive"], puts[0]["outcome"]) == (False, "replied"), "the first save left through the pagehide path: %r" % puts[0]
    filings = reqs(r, "TEST", r["id"], page="intake")
    assert len(filings) == 1 and filings[0]["outcome"] == "replied", "the project was not filed from the intake page: %r" % filings
    assert filings[0]["at"] >= puts[0]["repliedAt"], "the project was filed before it was saved"
    assert r["navs"][0]["askedAt"] >= filings[0]["repliedAt"], (
        "Continue left before the filing was answered: %r vs %r" % (r["navs"][0], filings[0]))


def test_a_slow_continue_is_unchanged(ran):
    """The path that always worked: 3.3 s after the last edit the autosave PUT has landed on the live intake and
    filed the project before Continue is pressed. Still filed, still not forked, the first save still the
    autosave's own (not the pagehide's), and the filing still sent before Continue."""
    r = ran["slow"]
    assert_filed_and_edited_directly(r, "slow")
    first = reqs(r, "PUT", r["id"])[0]
    assert first["keepalive"] is False and first["outcome"] == "replied" and first["at"] < r["continueAt"], first
    filing = reqs(r, "TEST", r["id"], page="intake")
    assert len(filing) == 1 and filing[0]["at"] < r["continueAt"], "the filing waited for Continue: %r" % filing


def test_a_slow_filing_is_waited_for(ran):
    """The filing is a SECOND request, and a page that leaves while it is in flight races the estimate page's
    first read of the row. With a server that takes 600 ms to file, the estimator must still arrive on a project
    that is filed."""
    assert_filed_and_edited_directly(ran["slowFiling"], "slowFiling")


def test_whatever_the_latencies_the_new_project_is_filed_and_never_forked(ran):
    """Sixteen runs: a slow save, a slow filing, both, a slow link, a next page that boots at once or late, and
    everything fast, each with Continue at 100 ms and at 700 ms. On 59922bd the answer depended on who was faster
    (a slow save happened to land a row the estimate page then saw as new, and filed itself); it must not.

    Not vacuous: on 59922bd more than half of these runs fork, so the sweep does reach the defect."""
    sweep = ran["sweep"]
    assert len(sweep) == 16 and len({s["combo"] for s in sweep}) == 8
    bad = []
    for s in sweep:
        ok = (s["x"] is not None and s["x"]["is_test"] is True and s["beta"] is None and s["intent"] is None
              and s["estimateDraft"] == s["id"] and DIRECT in (s["note"] or ""))
        if not ok:
            bad.append("%s, Continue at %d ms: project %s, copy %s, intent %r" % (s["combo"], s["waitMs"], s["x"], s["beta"], s["intent"]))
    assert not bad, "not filed and edited directly:\n  " + "\n  ".join(bad)


# ── Continue is never trapped ────────────────────────────────────────────────────────────────────────────
def test_a_server_that_never_answers_does_not_trap_the_estimator(ran):
    """Waiting for the save is bounded. The first PUT is never answered, and the estimator is on the estimate page
    within ten seconds of pressing Continue (the bound is SAVE_WAIT_MS in polish-intake.js), where the sandbox
    files the project it finds unsaved. Without a bound Continue would sit there until the browser gave up."""
    r = ran["hang"]
    assert len(r["navs"]) == 1, "Continue never left the intake: %r" % r["navs"]
    assert r["navs"][0]["askedAt"] - r["continueAt"] <= 10000, r["navs"][0]
    assert r["estimate"] and r["estimate"]["settled"] is True, r["estimate"]
    assert r["x"] is not None and r["x"]["is_test"] is True and r["beta"] is None, describe(r)


def test_a_save_that_fails_at_once_is_not_waited_out(ran):
    """No network: the first PUT fails immediately. Continue goes on at once (the local copy is safe, and the
    estimate page files what it finds unsaved), it does not sit out the bound."""
    r = ran["offline"]
    assert len(r["navs"]) == 1 and r["navs"][0]["askedAt"] - r["continueAt"] < 1000, r["navs"]
    assert r["x"] is not None and r["x"]["is_test"] is True and r["beta"] is None, describe(r)


# ── what is never claimed ────────────────────────────────────────────────────────────────────────────────
def test_a_filing_the_server_refused_is_not_reported_as_filed(ran):
    """The server answers every filing with HTTP 500. The project is left unfiled, and no page says otherwise: the
    estimate page is never on an unfiled project editing it as if it were a test, and never says "editing it
    directly" about one."""
    r = ran["failedFiling"]
    assert r["x"] is not None and r["x"]["is_test"] is None, describe(r)
    est = r["estimate"] or {}
    assert est.get("draftId") != r["id"] and DIRECT not in says(r), describe(r)
    assert COPY in says(r), "the estimate page does not say it moved the estimator onto a copy: " + describe(r)


def test_a_real_project_is_copied_and_never_written_to_or_filed(ran):
    """The sandbox's whole job, through the intake: a real project opened in v2 is copied, the copy is filed, and
    the real row is only ever READ, through Continue and onto the estimate page. (On 59922bd and after.)"""
    r = ran["realThroughIntake"]
    assert r["real"] == {"is_test": None, "beta_sandbox_of": None, "project_name": "Nearman Creek"}
    assert r["realAddress"] == "1 Water Works Dr", "the real project's row was written to"
    assert [q for q in reqs(r, id_="real-1") if q["method"] != "GET"] == [], "the real project was written to or filed"
    assert r["beta"] == {"is_test": True, "beta_sandbox_of": "real-1", "project_name": "Nearman Creek (beta test)"}
    assert r["draftOnOpen"] == "real-1-beta" and COPY in r["noteOnOpen"]
    assert (r["estimate"] or {}).get("draftId") == "real-1-beta" and r["intent"] is None
