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
pages after everything has settled. On 59922bd the model reproduces X1 (both fast flows fork), which is what makes
its green on the fix worth something; its browser rules and its server are held to the real thing by the first tests
below (what a browser does with a page it is leaving, and the real routes of backend/main.py answering the same
requests). The MUTATION tests at the end break a COPY of the sources, one or two lines at a time, and require a named
check to go red.
"""
import pathlib
import re
import shutil

import pytest

from fastapi.testclient import TestClient

import drafts
import main
from _golden_support import FRONTEND, break_source
from _node import last_json_line, require_node, run_node

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parents[1]
HARNESS = TESTS / "js" / "new-estimate-test-flag-harness.js"
INTAKE_HARNESS = TESTS / "js" / "polish-intake-harness.js"
# What each harness reads from a frontend directory (they do not fall back to the real one), so that a scratch
# copy that breaks ONE file can be completed with the rest.
PAGE_FILES = ["shared.js", "polish-intake.html", "js/polish-intake.js", "js/polish-sandbox.js", "js/work-types.js",
              "js/intake-scope.js", "js/bid-model.js", "js/excel-math.js"]
INTAKE_FILES = ["shared.js", "polish-intake.html", "js/polish-intake.js", "js/bid-model.js", "js/work-types.js",
                "js/polish-sandbox.js", "js/intake-scope.js", "js/county-picker.js"]
client = TestClient(main.app)
INTENT_KEY = "treadwell.proposal_tool.new_is_test"
DIRECT = "editing it directly"            # showDirectNote(false): "... Estimating Tool v2 is editing it directly."
COPY = "test copy"                        # showCopyNote: "You are editing a test copy. ..."


def run(frontend=FRONTEND):
    proc = run_node(HARNESS, frontend, timeout=600)
    assert proc.returncode == 0, "the harness itself failed. Read this before assuming a product bug:\n" + proc.stderr[-1500:]
    return last_json_line(proc.stdout)


def run_intake(frontend=FRONTEND):
    proc = run_node(INTAKE_HARNESS, frontend, timeout=600)
    assert proc.returncode == 0, "the intake harness itself failed:\n" + proc.stderr[-1500:]
    return last_json_line(proc.stdout)


@pytest.fixture(scope="module")
def ran():
    require_node()
    return run()


@pytest.fixture(scope="module")
def intake():
    require_node()
    return run_intake()


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


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    """The real routes over the in-memory fake (conftest), never the live client: see test_projects_test_flag.py."""
    st = {"drafts": [], "events": []}
    monkeypatch.setattr(drafts, "get_client", lambda: fake_supabase(st))
    return st


def test_the_model_answers_like_the_real_routes(ran, store):
    """The same five requests, sent to backend/main.py's real routes (over the in-memory store) and to the model:
    a read of a project nobody saved, the first save, a read of what was saved, filing it, and filing a project that
    is not there. Status codes agree, the filing answers are equal, a save answers the same keys, and what the
    model's read hands back is a subset of the real one's (the pages read `data` and `updated_at`). A model of a
    server that answered differently from the server would prove the fix against a server that is not there."""
    got = ran["model"]["routeAnswers"]
    real = {}
    r = client.get("/api/draft/m1")
    real["getMissing"] = {"status": r.status_code, "keys": sorted(r.json())}
    r = client.put("/api/draft/m1", json={"data": {"project_name": "A"}})
    real["putNew"] = {"status": r.status_code, "keys": sorted(r.json()), "body": r.json()}
    r = client.get("/api/draft/m1")
    real["getThere"] = {"status": r.status_code, "keys": sorted(r.json()), "body": r.json()}
    r = client.post("/api/draft/m1/test", json={"is_test": True})
    real["fileThere"] = {"status": r.status_code, "body": r.json()}
    r = client.post("/api/draft/m2/test", json={"is_test": True})
    real["fileMissing"] = {"status": r.status_code, "body": r.json()}

    assert (got["getMissing"]["status"], got["getMissing"]["keys"]) == (real["getMissing"]["status"], real["getMissing"]["keys"])
    assert got["putNew"]["status"] == real["putNew"]["status"] == 200
    assert got["putNew"]["keys"] == real["putNew"]["keys"], (got["putNew"]["keys"], real["putNew"]["keys"])
    assert got["getThere"]["status"] == real["getThere"]["status"] == 200
    assert set(got["getThere"]["keys"]) <= set(real["getThere"]["keys"]) and {"ok", "data", "updated_at"} <= set(got["getThere"]["keys"])
    assert got["getThere"]["body"]["data"] == real["getThere"]["body"]["data"] == {"project_name": "A"}
    for key in ("fileThere", "fileMissing"):
        assert got[key]["status"] == real[key]["status"] == 200, key
        assert got[key]["body"] == real[key]["body"], (key, got[key]["body"], real[key]["body"])
    assert real["fileThere"]["body"] == {"ok": True, "existed": True, "is_test": True}
    assert real["fileMissing"]["body"] == {"ok": True, "existed": False, "is_test": True}


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
    assert 'if (TAB === "gc") localStorage.setItem("treadwell.proposal_tool.state", JSON.stringify({ audience: "GC" }));' in body, (
        "the GC tab no longer starts a bid with { audience: GC } in the draft")


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
def test_a_fast_continue_files_the_new_project_under_test(ran):
    """THE DEFECT. Continue 100 ms after the last edit (nothing has been saved), and at 700 ms (the 600 ms autosave
    has run and the 2.5 s timer that sends it is armed): the project is filed under Test, nothing is forked, the
    intent is used up and the estimate page says it is editing the test project directly.

    Red on 59922bd: the project sits unfiled, est-1-beta exists, and the estimate page says "You are editing a
    test copy ... The real project ... is untouched in Active"."""
    for flow in ("fast", "fastAfterAutosave"):
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


def test_a_new_gc_estimate_is_filed_as_the_page_opens_and_stays_filed(ran):
    """The GC tab's + New leaves { audience: "GC" } in the draft before the intake opens, so the sandbox has something
    to save: it saves the project and files it at once, and no filing is left pending (the intent is for a project
    with nothing in it). A fast Continue after that leaves the project as it is: filed, nothing forked, and the
    first save was the sandbox's, before Continue was pressed."""
    r = ran["gcTab"]
    assert_filed_and_edited_directly(r, "gcTab")
    first = reqs(r, "PUT", r["id"])[0]
    assert first["at"] < r["continueAt"] and first["keepalive"] is False and first["outcome"] == "replied", first
    assert r["pendingAtOpen"] is None, "a filing was left pending for a project that is filed as the page opens"


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
@pytest.mark.parametrize("mode", ["http500", "okfalse", "network"])
def test_a_filing_the_server_would_not_do_is_not_reported_as_filed(ran, mode):
    """The server will not file the project: HTTP 500, a 200 carrying {"ok": false} (how the route answers a caught
    exception), or no network. The project is left unfiled, Continue still leaves at once, and no page says
    otherwise: the estimate page is never on an unfiled project editing it as if it were a test, and never says
    "editing it directly" about one. (It moves the estimator onto a copy, which is the sandbox's answer to a project
    nobody has filed, and says so.)"""
    r = ran["failedFiling"][mode]
    assert r["x"] is not None and r["x"]["is_test"] is None, describe(r)
    est = r["estimate"] or {}
    assert est.get("draftId") != r["id"] and DIRECT not in says(r), describe(r)
    assert COPY in says(r), "the estimate page does not say it moved the estimator onto a copy: " + describe(r)
    assert len(r["navs"]) == 1 and r["navs"][0]["askedAt"] - r["continueAt"] < 1000, r["navs"]


def test_a_filing_nobody_answers_does_not_trap_the_estimator_either(ran):
    """The save is answered and the filing that follows it is not. Waiting is bounded for this too: the estimator is
    on the estimate page within ten seconds of pressing Continue, the project is still unfiled, and nothing says
    it is filed."""
    r = ran["hangFiling"]
    assert len(r["navs"]) == 1, "Continue never left the intake: %r" % r["navs"]
    assert r["navs"][0]["askedAt"] - r["continueAt"] <= 10000, r["navs"][0]
    assert r["x"] is not None and r["x"]["is_test"] is None, describe(r)
    assert DIRECT not in says(r) and (r["estimate"] or {}).get("draftId") != r["id"], describe(r)


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


# ══ T2: the net under every other way out of the intake ════════════════════════════════════════════════
REAL_PROJECT = "proj-9"
FAILURE = "filing it under the Test tab did not work"      # the sentence showCopyNote adds when the filing failed


def test_the_estimate_page_files_a_new_project_the_intake_left_unfiled(ran):
    """The "2 · Estimate" step link 700 ms after the last edit: Continue is not the only door out of the intake, and
    this one waits for nothing, so the first PUT goes out as the page goes and the project is saved, unfiled, with the
    pending filing still in storage. The estimate page's sandbox finds exactly that and files the project instead of
    forking it: filed, nothing forked, the intent used up, and the page says it is editing the test project directly.

    Red without the net (js/polish-sandbox.js): the project sits unfiled and a "(beta test)" copy is made of it."""
    r = ran["pill"]
    first = reqs(r, "PUT", r["id"], page="intake")[0]
    assert (first["keepalive"], first["outcome"]) == (True, "reply dropped"), (
        "the run does not start from the state the net is for (a project saved by the pagehide path): %r" % first)
    assert_filed_and_edited_directly(r, "pill")
    filing = reqs(r, "TEST", r["id"])
    assert len(filing) == 1 and filing[0]["page"].startswith("estimate") and filing[0]["outcome"] == "replied", filing
    assert r["estimate"]["settledAt"] >= filing[0]["repliedAt"], "the page said so before the server had answered"


def test_the_intake_files_a_project_it_is_opened_on_after_the_tab_was_closed(ran):
    """The tab goes as the first PUT is sent (the same keepalive request), and the board's link to the project is
    followed a minute later. The v2 INTAKE'S own sandbox is the one that finds the project saved and unfiled: it
    files it, edits it directly, and does not fork it."""
    r = ran["closedThenReopened"]
    assert r["before"]["x"]["is_test"] is None and r["before"]["beta"] is None and r["before"]["intent"] == r["id"] + ":1", (
        "the run does not start from a saved, unfiled project with its filing pending: %r" % r["before"])
    assert r["x"]["is_test"] is True and r["beta"] is None and r["intent"] is None, describe(r)
    assert r["intakeDraft"] == r["id"] and DIRECT in r["intakeNote"] and COPY not in r["intakeNote"], (r["intakeDraft"], r["intakeNote"])


def test_the_door_that_always_worked_still_does(ran):
    """The same step link 100 ms after the last edit: nothing is queued yet, the page's own pagehide save is a plain
    request and goes with the page, so the estimate page finds NO row, and the sandbox saves and files what it holds.
    Filed and not forked, before the net and after it."""
    r = ran["pillFast"]
    assert r["x"] is not None and r["x"]["is_test"] is True and r["beta"] is None, describe(r)
    assert (r["estimate"] or {}).get("draftId") == r["id"] and DIRECT in says(r), describe(r)


# (run, what the real row's is_test is, what is left pending in storage)
REAL_CASES = [
    ("realProject", None, None),
    ("anotherProjects", None, "other-1:1"),
    ("saidReal", False, REAL_PROJECT + ":1"),
    ("filingAsReal", None, REAL_PROJECT + ":0"),
]


def test_a_real_project_is_copied_never_filed_and_never_written_to(ran):
    """THE RULE THE NET MUST NOT BREAK. A project nobody here made as a new test project, whatever else is in
    storage, is a real bid: the sandbox copies it as it always did, files the copy, and never writes to the real row.
      realProject      nothing pending at all
      anotherProjects  ANOTHER project's filing is pending: it is neither used nor lost
      saidReal         a human filed this one as a real bid (is_test false) and its own filing is still pending
      filingAsReal     the pending filing says "real" ("<id>:0", the Active tab's New project), not "test"
    In every one the real row is read and nothing else: no save, no filing, and its is_test is what it was."""
    for scenario, is_test, pending in REAL_CASES:
        r = ran[scenario]
        assert r["x"] == {"is_test": is_test, "beta_sandbox_of": None, "project_name": "Wichita Warehouse"}, (scenario, r["x"])
        assert [q for q in reqs(r, id_=REAL_PROJECT) if q["method"] != "GET"] == [], (
            "%s: the real project was written to or filed" % scenario)
        assert r["beta"] == {"is_test": True, "beta_sandbox_of": REAL_PROJECT,
                             "project_name": "Wichita Warehouse (beta test)"}, (scenario, r["beta"])
        est = r["estimate"] or {}
        assert est.get("draftId") == REAL_PROJECT + "-beta" and COPY in says(r) and DIRECT not in says(r), (
            "%s: %s" % (scenario, describe(r)))
        assert r["intent"] == pending, "%s: the pending filing was used up or changed: %r, was %r" % (scenario, r["intent"], pending)


def test_a_filing_the_estimate_page_could_not_do_is_said_and_never_claimed(ran):
    """The net's own filing fails: HTTP 500, a 200 carrying {"ok": false}, no network, a 200 that is not JSON (a
    proxy's error page), and a 200 that says there is no such row. In every one the project is left unfiled and
    the page does not pretend: it does what it does for any unfiled project (a copy, which it says it is) and adds
    that this project was meant to be a test and could not be filed. Nothing says "editing it directly". The pending
    filing is NOT used up, so the next time the project is opened it is tried again."""
    assert sorted(ran["unfiled"]) == ["gone", "html", "http500", "network", "okfalse"]
    for mode, r in sorted(ran["unfiled"].items()):
        est = r["estimate"] or {}
        assert r["x"] is not None and r["x"]["is_test"] is None, "%s: the project was filed, or its row is gone: %s" % (mode, describe(r))
        assert est.get("draftId") == r["id"] + "-beta" and COPY in says(r) and DIRECT not in says(r), "%s: %s" % (mode, describe(r))
        assert FAILURE in says(r), "%s: the page does not say the filing failed: %r" % (mode, says(r))
        assert r["intent"] == r["id"] + ":1", "%s: the pending filing was used up by a filing that failed: %r" % (mode, r["intent"])


def test_no_flow_reloads_the_page_in_a_loop(ran):
    """Not a check of the fix, a check of the model's runs: shared.js hydrates a project and reloads, and anything
    that claims the one storage slot in between would have it do that for ever. Every run ends."""
    flows = [ran[k] for k in ("fast", "fastAfterAutosave", "slow", "slowFiling", "hang", "offline", "hangFiling",
                              "realThroughIntake", "pill", "pillFast", "closedThenReopened", "realProject",
                              "anotherProjects", "saidReal", "filingAsReal")]
    flows += list(ran["failedFiling"].values()) + list(ran["unfiled"].values()) + ran["sweep"]
    assert [f for f in flows if f.get("runaway")] == []


def test_a_copy_is_edited_directly_and_nothing_is_filed_for_it(ran):
    """A test copy whose own filing is somehow pending (it never is: nothing writes one for a copy) is still what it
    always was to the sandbox: edited directly, with no filing sent for it. The net is for a project this browser made
    as a new test project, and a copy is not one."""
    r = ran["aCopy"]
    assert r["x"] == {"is_test": None, "beta_sandbox_of": "some-real-project", "project_name": "Wichita Warehouse (beta test)"}, r["x"]
    assert reqs(r, "TEST", REAL_PROJECT) == [], "a filing was sent for a copy"
    assert (r["estimate"] or {}).get("draftId") == REAL_PROJECT and DIRECT in says(r), describe(r)
    assert r["intent"] == REAL_PROJECT + ":1"


def _sandbox_code():
    return (FRONTEND / "js" / "polish-sandbox.js").read_text(encoding="utf-8")


def test_the_three_places_that_name_the_pending_filing_agree():
    """shared.js owns the pending filing, the sandbox's markNewProjectAsTest writes it and its net reads it. Three
    spellings of one key: if they drift apart the intent is written where nothing reads it, and the net quietly never
    fires (the pill and reopened runs above would still be red, but for a reason nobody could see in the diff)."""
    shared = (FRONTEND / "shared.js").read_text(encoding="utf-8")
    sandbox = _sandbox_code()
    keys = {
        "shared.js NEW_IS_TEST_KEY": re.search(r'const NEW_IS_TEST_KEY = "([^"]+)";', shared).group(1),
        "markNewProjectAsTest": re.search(r'function markNewProjectAsTest\(id\) \{\s*try \{ localStorage\.setItem\("([^"]+)", id \+ ":1"\)',
                                          sandbox).group(1),
        "the net's NEW_TEST_KEY": re.search(r'var NEW_TEST_KEY = "([^"]+)";', sandbox).group(1),
    }
    assert len(set(keys.values())) == 1 and INTENT_KEY in keys.values(), keys


def test_the_net_stands_between_the_missing_row_and_the_filed_as_test_check():
    """Where the net is called matters as much as what it does. After the never-saved branch (a row that does not
    exist has nothing to file) and before the page commits to editing a row directly, which it does for a row that is
    already filed and for a copy, both of which the net leaves alone. test_polish_beta_sandbox.py reads the slice from
    the filed-as-test check down for writes to the page's own id, and the net is the one filing that is not in it."""
    body = _sandbox_code()
    body = body[body.index("async function enterSandbox"):]
    order = [body.index("if (row === null) {"), body.index("await fileOwnNewProject(id, row)"),
             body.index("row.is_test === true || row.beta_sandbox_of"), body.index("sandboxIdFor(id)")]
    assert order == sorted(order), order


# ══ the intake page alone: what Continue does with the answer to its save ═════════════════════════════
def test_continue_saves_first_waits_for_the_answer_and_then_leaves(intake):
    """The REAL onSubmit, lifted into tests/js/polish-intake-harness.js with a save the test answers BY HAND:
    save() runs at once (the page's own copy is written before anything is waited for), nothing has been sent to
    the estimate page while the save is out, the page's own bound is the only timer armed, and when the answer
    comes Continue leaves for the estimate page on the right draft and clears the timer."""
    c = intake["continueWaits"]
    assert c["whileWaiting"] == {"navigated": 0, "savedFirst": 1, "flushes": 1, "armed": 1}, c["whileWaiting"]
    assert c["afterAnswer"] == {"navigated": ["/polish-estimate.html?d=proj-1"], "armed": 0}, c["afterAnswer"]


def test_continue_leaves_when_the_wait_is_over_however_it_ends(intake):
    """Four endings the real flushState or the clock can produce. A save nobody answers is let go by the page's own
    bound (and not before it); a save that failed (flushState answers false) and a save that threw (it never does,
    so this is the page's own `catch`, which no other test reaches) both leave at once; and in all of them the
    wait's timer is cleared."""
    c = intake["continueWaits"]
    assert c["neverAnswered"] == {"beforeBound": 0, "afterBound": ["/polish-estimate.html?d=proj-1"], "armedAfter": 0}, c["neverAnswered"]
    assert c["failedSave"] == {"navigated": ["/polish-estimate.html?d=proj-1"], "armedAfter": 0}, c["failedSave"]
    assert c["threw"] == {"navigated": ["/polish-estimate.html?d=proj-1"], "armedAfter": 0, "saved": True}, c["threw"]


# ══ every check goes red when the code is changed ═════════════════════════════════════════════════════
# Each entry breaks one or more LINES of the sources in a scratch copy of the frontend, runs a harness on it, and the
# named check (a test above, called on the broken run's answers) has to fail. break_source refuses an anchor that is not
# there exactly once, so none of them can pass by applying nowhere; the harness runs outside the `raises`, so a break
# that merely crashes it is an error and never counts as the check noticing.
#
# TWO LAYERS, SO TWO KINDS OF ENTRY. Continue's wait (T1) and the sandbox's net (T2) each make a fast Continue end
# filed and unforked, so breaking ONE of them does not move that end state, which is the point of having both. What
# breaks one is seen in how it got there (the first save is a plain request answered to a page that is still there; the
# filing is answered before the page leaves). The end state itself is shown by an entry that breaks BOTH.
FLUSH_LINE = "        TW.flushState(),"
BOUND_LINE = "        new Promise(function (resolve) { timer = setTimeout(resolve, SAVE_WAIT_MS); })"
CLEAR_LINE = "    if (timer) clearTimeout(timer);"
CATCH_LINE = "    } catch (err) { /* flushState reports a failed save as false; it does not throw */ }"
AWAIT_FILING_LINE = "        if (ok) await applyPendingTestIntent(id);"

NET_CALL = "    var filedNow = await fileOwnNewProject(id, row);"
NET_NOT_A_COPY = "    if (!row || row.beta_sandbox_of) return null;"
NET_UNSET = "    if (row.is_test != null) return null;"
NET_PENDING = "    if (!newTestPending(id)) return null;"
NET_BINDING = '    try { return localStorage.getItem(NEW_TEST_KEY) === id + ":1"; } catch (e) { return false; }'
NET_BODY = "      if (!body || body.ok !== true || body.existed === false) {"
NET_WARN = '      console.warn("[polish beta] could not file the new project as a test", e);'
NET_FORGET = "    forgetNewTest(id);"
NET_DIRECT = "    if (filedNow === true) {"
NET_NOTE = "    showCopyNote(row.project_name, state.project_name, filedNow === false);"

SANDBOX = "js/polish-sandbox.js"
INTAKE = "js/polish-intake.js"
SHARED = "shared.js"


def broken(rel, old, new):
    return (rel, old, new)


# name -> (harness, (the lines to break: (file, anchor line, what it becomes), ...), the check)
BREAKS = {
    # ── T1: Continue waits for the save and the filing ──
    "Continue leaves without waiting for the save": (
        "world", (broken(INTAKE, FLUSH_LINE, "        Promise.resolve(true),"),),
        test_the_first_save_and_its_filing_are_answered_to_a_page_that_is_still_there),
    "Continue does not wait and nothing else catches the project": (
        "world", (broken(INTAKE, FLUSH_LINE, "        Promise.resolve(true),"),
                  broken(SANDBOX, NET_CALL, "    var filedNow = null;")),
        test_a_fast_continue_files_the_new_project_under_test),
    "the save is waited for and the filing that follows it is not": (
        "world", (broken(SHARED, AWAIT_FILING_LINE, "        if (ok) applyPendingTestIntent(id);"),),
        test_a_slow_filing_is_waited_for),
    "the answer depends on who is faster (the filing is not waited for)": (
        "world", (broken(SHARED, AWAIT_FILING_LINE, "        if (ok) applyPendingTestIntent(id);"),),
        test_whatever_the_latencies_the_new_project_is_filed_and_never_forked),
    "Continue waits for a save that never answers, for ever": (
        "world", (broken(INTAKE, BOUND_LINE, "        new Promise(function () {})"),),
        test_a_server_that_never_answers_does_not_trap_the_estimator),
    "Continue waits for a filing that never answers, for ever": (
        "world", (broken(INTAKE, BOUND_LINE, "        new Promise(function () {})"),),
        test_a_filing_nobody_answers_does_not_trap_the_estimator_either),
    "Continue does not wait for the save (the page alone)": (
        "intake", (broken(INTAKE, FLUSH_LINE, "        Promise.resolve(true),"),),
        test_continue_saves_first_waits_for_the_answer_and_then_leaves),
    "Continue's wait has no bound (the page alone)": (
        "intake", (broken(INTAKE, BOUND_LINE, "        new Promise(function () {})"),),
        test_continue_leaves_when_the_wait_is_over_however_it_ends),
    "Continue leaves its wait's timer armed": (
        "intake", (broken(INTAKE, CLEAR_LINE, "    void 0;"),),
        test_continue_saves_first_waits_for_the_answer_and_then_leaves),
    "a save that throws stops Continue": (
        "intake", (broken(INTAKE, CATCH_LINE, "    } catch (err) { return; }"),),
        test_continue_leaves_when_the_wait_is_over_however_it_ends),
    # ── T2: the sandbox's net ──
    "the net is never called": (
        "world", (broken(SANDBOX, NET_CALL, "    var filedNow = null;"),),
        test_the_estimate_page_files_a_new_project_the_intake_left_unfiled),
    "the net is never called (a project reopened after its tab was closed)": (
        "world", (broken(SANDBOX, NET_CALL, "    var filedNow = null;"),),
        test_the_intake_files_a_project_it_is_opened_on_after_the_tab_was_closed),
    "the net files a project whether or not this browser made it": (
        "world", (broken(SANDBOX, NET_PENDING, "    void 0;"),),
        test_a_real_project_is_copied_never_filed_and_never_written_to),
    "the pending filing is read as any project's": (
        "world", (broken(SANDBOX, NET_BINDING,
                         "    try { return /:1$/.test(localStorage.getItem(NEW_TEST_KEY) || \"\"); } catch (e) { return false; }"),),
        test_a_real_project_is_copied_never_filed_and_never_written_to),
    "a pending filing that says real counts as one that says test": (
        "world", (broken(SANDBOX, NET_BINDING,
                         "    try { return (localStorage.getItem(NEW_TEST_KEY) || \"\").indexOf(id + \":\") === 0; } catch (e) { return false; }"),),
        test_a_real_project_is_copied_never_filed_and_never_written_to),
    "a project a human filed as real is filed again": (
        "world", (broken(SANDBOX, NET_UNSET, "    if (row.is_test === true) return null;"),),
        test_a_real_project_is_copied_never_filed_and_never_written_to),
    "the net acts on a copy": (
        "world", (broken(SANDBOX, NET_NOT_A_COPY, "    if (!row) return null;"),),
        test_a_copy_is_edited_directly_and_nothing_is_filed_for_it),
    "the net takes a 200 for a filing": (
        "world", (broken(SANDBOX, NET_BODY, "      if (false) {"),),
        test_a_filing_the_estimate_page_could_not_do_is_said_and_never_claimed),
    "the net takes a row that is not there for a filed one": (
        "world", (broken(SANDBOX, NET_BODY, "      if (!body || body.ok !== true) {"),),
        test_a_filing_the_estimate_page_could_not_do_is_said_and_never_claimed),
    "a filing that failed uses up the pending filing": (
        "world", (broken(SANDBOX, NET_WARN, NET_WARN + " forgetNewTest(id);"),),
        test_a_filing_the_estimate_page_could_not_do_is_said_and_never_claimed),
    "a filing that worked leaves the pending filing": (
        "world", (broken(SANDBOX, NET_FORGET, "    void 0;"),),
        test_the_estimate_page_files_a_new_project_the_intake_left_unfiled),
    "a project that could not be filed is edited directly": (
        "world", (broken(SANDBOX, NET_DIRECT, "    if (filedNow !== null) {"),),
        test_a_filing_the_estimate_page_could_not_do_is_said_and_never_claimed),
    "a filing that failed is not said": (
        "world", (broken(SANDBOX, NET_NOTE, "    showCopyNote(row.project_name, state.project_name);"),),
        test_a_filing_the_estimate_page_could_not_do_is_said_and_never_claimed),
}


def _break_more(frontend, rel, old, new):
    """Another line broken in the scratch copy break_source made: the same rule, the anchor is there exactly once."""
    target = frontend / rel
    src = target.read_bytes().decode("utf-8")
    seen = src.count(old)
    assert seen == 1, "the mutation anchor %r appears %d times in %s, not once" % (old, seen, rel)
    target.write_bytes(src.replace(old, new).encode("utf-8"))


def _on_broken_tree(tmp_path, which, edits):
    files = PAGE_FILES if which == "world" else INTAKE_FILES
    rel, old, new = edits[0]
    frontend = break_source(tmp_path, rel, old, new, also=files)
    for rel, old, new in edits[1:]:
        _break_more(frontend, rel, old, new)
    if which == "intake":
        # the intake harness parses the county table out of backend/reference_tax.py, beside the frontend
        (tmp_path / "backend").mkdir(exist_ok=True)
        shutil.copyfile(ROOT / "backend" / "reference_tax.py", tmp_path / "backend" / "reference_tax.py")
    return run(frontend) if which == "world" else run_intake(frontend)


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_checks_go_red_when_the_code_changes(tmp_path, name):
    require_node()
    which, edits, check = BREAKS[name]
    broken_answer = _on_broken_tree(tmp_path, which, edits)
    with pytest.raises(AssertionError):
        check(broken_answer)


def test_the_unbroken_answers_pass_every_check_the_table_names(ran, intake):
    """The other half: the same checks, called the same way, are green on the real code."""
    real = {"world": ran, "intake": intake}
    for which, _edits, check in BREAKS.values():
        check(real[which])


def test_every_check_a_break_names_is_a_real_test_and_each_part_of_the_fix_has_a_break():
    named = {check.__name__ for _which, _edits, check in BREAKS.values()}
    for must in (test_a_fast_continue_files_the_new_project_under_test,
                 test_the_first_save_and_its_filing_are_answered_to_a_page_that_is_still_there,
                 test_a_slow_filing_is_waited_for,
                 test_whatever_the_latencies_the_new_project_is_filed_and_never_forked,
                 test_a_server_that_never_answers_does_not_trap_the_estimator,
                 test_a_filing_nobody_answers_does_not_trap_the_estimator_either,
                 test_continue_saves_first_waits_for_the_answer_and_then_leaves,
                 test_continue_leaves_when_the_wait_is_over_however_it_ends,
                 test_the_estimate_page_files_a_new_project_the_intake_left_unfiled,
                 test_the_intake_files_a_project_it_is_opened_on_after_the_tab_was_closed,
                 test_a_real_project_is_copied_never_filed_and_never_written_to,
                 test_a_copy_is_edited_directly_and_nothing_is_filed_for_it,
                 test_a_filing_the_estimate_page_could_not_do_is_said_and_never_claimed):
        assert must.__name__ in named, "no break turns %s red" % must.__name__


def test_every_anchor_a_break_uses_is_still_one_line_of_its_file():
    """The anchors are lines of the real sources, and a break_source run would refuse one that moved. This says it
    without running a harness: every entry's anchor is a single line, found exactly once, in the file it names."""
    for name, (_which, edits, _check) in sorted(BREAKS.items()):
        for rel, old, _new in edits:
            src = (FRONTEND / rel).read_bytes().decode("utf-8")
            assert "\n" not in old and "\r" not in old, name
            assert src.count(old) == 1, "%s: %r is in %s %d times" % (name, old, rel, src.count(old))
