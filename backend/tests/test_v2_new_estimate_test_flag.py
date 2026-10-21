"""X1 -- A NEW v2 ESTIMATE IS FILED UNDER TEST FROM THE INSTANT IT EXISTS, HOWEVER THE ESTIMATOR LEAVES THE INTAKE.

THE DEFECT, walked on staging 59922bd (2026-10-21). "New estimate" on the v2 board opens the v2 intake for a NEW project,
and the intake says it is "saved as a NEW test project, under the Test tab". Press Continue within about three seconds
of the last edit and the project sat on the Direct Projects board where staff work, unfiled, and the estimate page
forked a "(beta test)" copy of it ("You are editing a test copy ... The real project ... is untouched in Active").

ROUND 1 (T1, T2) kept the promise with a SECOND REQUEST: an intent that shared.js turned into a POST /test once the first
PUT came back, from a page that had to still be there to see it come back. Continue waited for it (T1) and the estimate
page filed what it found unfiled (T2). The audit of round 1 found that every door that did not wait left a row BORN
UNFILED (a double press, a press while the autosave was in flight, a link, Back, a closed tab: F1, F2), that a filing that
failed was never read (F3), that putDraft waiting on the filing held the NEXT page's boot hostage (F4), that Continue gave
no sign it was waiting (F5), that the net would file a stale intent's project (F6), and that none of it was pinned (F7).

THE FIX (round 2) IS THE SEED, which removes the second request. shared.js's setState puts what the browser started the
project as into the project's OWN blob from its first write (is_test true for a project started as a test, false for one
started from the Active tab, nothing for All and Inactive), and the intent that carried it is used up on the spot. The
backend inserts a new row as sent and, on an update, keeps a server-owned key the row already has (drafts.save_draft,
keep_server_owned), so the first PUT, by whatever path it leaves, CREATES THE ROW ALREADY FILED, and a project somebody has
since filed as real is never re-flagged by a stale blob. No page's boot, no button and no door has anything to wait for,
and a failed filing is a failed save, which is read as one. Of round 1, T1's wait stays (the first save is on the server
before the browser leaves, answered to a page that is still there) with feedback on the button, and the sandbox's net (T2)
is gone: it had nothing left to catch, and it filed whatever a stale intent named, from inside the next page's boot.

THE AUDIT OF ROUND 2 (11 of its 14 claims held) found five more ways to file a project wrongly, and ROUND 3 closes them. The seed was kept
in ONE localStorage slot ("<id>:<0|1>"), and the slot was the weak point: (F1) a page that only LOOKED at a project overwrote it, so a
real bid started on the Active tab was born a test after a look at a v2 page; (F2) a blob that never went through setState (the GC
board's { audience: "GC" }) had nowhere to carry it, so flushing it when another project was opened created it unfiled; (F3) a second
tab's New project overwrote the first tab's start before its first write; (F4) /api/generate's write-back put a payload's old is_test
over a person's filing; (F5) the intake's pagehide save was a plain request, which a page that is going cannot finish. Now each
project's start is its OWN key, minted together with its id as New project is pressed; a v2 page's own word ("this page created the
project") is held in that page's memory and goes into the first write that page makes, so a look arms nothing; putDraft puts the start
on a copy that never went through setState and spends it only once the server has stored the copy; the write-back keeps what a person
filed (test_generate_writeback.py); and the pagehide saves are keepalive requests (a draft too big for one goes plain). By design,
pinned: a project typed into on a v2 page is a test project whichever tab started it. Only a LOOK leaves it as its tab started it.

HOW THESE TESTS RUN. tests/js/new-estimate-test-flag-harness.js runs the REAL shared.js, js/polish-sandbox.js,
js/polish-intake.js and js/index.js, whole, in tests/js/_world.js: a browser model with virtual time in which a page's
timers and replies die with it and a keepalive request survives it with nobody to hear the answer. The intake is driven as
a person drives it; every fact is read off the server's rows (what each was BORN as, and what it is now) and the pages after
everything has settled. Round 3 adds the model's TABS (one localStorage, a sessionStorage and a page per tab) and runs the real
Projects-page and board starts (js/projects.js's "+ New project" handler and js/portal.js's startNewProposal, lifted out of their
files). The model's SERVER is held to the real routes by the first tests below (the same requests go to
backend/main.py over an in-memory store). Its BROWSER rules (a page being left, keepalive, a reply nobody sees) are only stated
by the first of them: nothing in this suite can check a browser against the model, so they were walked by hand in a real Chrome
on 2026-10-21 (the fast Continue, the step link, a closed tab, the live intake from the Test tab, a navigation that does not go),
against the real backend over an in-memory store, and each agreed with the model.
The MUTATION tests at the end break a COPY of the sources, one line at a time, and require a named check to go red.
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
PAGE_FILES = ["shared.js", "polish-intake.html", "index.html", "js/polish-intake.js", "js/polish-sandbox.js", "js/index.js",
              "js/projects.js", "js/portal.js", "js/v2-board.js", "js/work-types.js", "js/intake-scope.js", "js/bid-model.js",
              "js/excel-math.js"]
INTAKE_FILES = ["shared.js", "polish-intake.html", "js/polish-intake.js", "js/bid-model.js", "js/work-types.js",
                "js/polish-sandbox.js", "js/intake-scope.js", "js/county-picker.js"]
client = TestClient(main.app)
INTENT_KEY = "treadwell.proposal_tool.new_is_test"
DIRECT = "editing it directly"            # showDirectNote(false): "... Estimating Tool v2 is editing it directly."
COPY = "test copy"                        # showCopyNote: "You are editing a test copy. ..."
UNSAVED = "has not been saved to the server yet"      # the sentence the estimate page says when a new project could not be saved
SAVING = "Saving…"                   # Continue while it waits for its save
OPENING = "Opening the estimate…"    # ... and once it has asked the browser to leave


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
    """A run in one line, for a failure message: the project, its copy, and what the estimate page said."""
    e = r["estimate"] or {}
    return "project %s, beta copy %s, estimate page on %s said %r" % (r["x"], r["beta"], e.get("draftId"), says(r)[:90])


def assert_born_filed(r, flow):
    """THE PROMISE, as a fact about the row's BIRTH: the project the estimator started was created already filed under
    Test (its first save said so), nothing had to file it afterwards, no beta copy exists, and it is the only row."""
    x = r["x"]
    assert x is not None, "%s: no row for the new project: %s" % (flow, describe(r))
    assert x["bornIsTest"] is True, "%s: the project was created UNFILED (on the board where staff work): %s" % (flow, describe(r))
    assert x["is_test"] is True and x["flips"] == 0, "%s: the project is not filed, or a second request had to file it: %s" % (flow, describe(r))
    assert r["beta"] is None and r["rowIds"] == [r["id"]], "%s: a beta copy was forked, or another row appeared: %s" % (flow, describe(r))


def assert_filed_and_edited_directly(r, flow):
    """... and the estimate page is on that very project and says it is editing a test project directly."""
    assert_born_filed(r, flow)
    est = r["estimate"] or {}
    assert est.get("settled") is True and est.get("draftId") == r["id"], "%s: the estimate page is not on the project: %s" % (flow, describe(r))
    assert DIRECT in says(r) and COPY not in says(r), "%s: the estimate page does not say it is editing the test project directly: %s" % (flow, describe(r))


# ══ the model ════════════════════════════════════════════════════════════════════════════════════════════
def test_the_model_is_a_browser_that_drops_what_a_browser_drops(ran):
    """If the model were kinder than a browser, X1 could not be reproduced here; if it were harsher, the fix could
    be right for the wrong reason. So it is held to what a browser does with a page it is leaving: the old page
    keeps running until the new document commits (a reply that comes back in that time is SEEN), a request that
    had reached the server is finished whatever happens to the page, a reply to a page that has gone is seen by
    nobody, a keepalive request sent as the page goes survives it and a plain one does not, a timer of a page
    that has gone never fires, and a load that is stopped leaves the page where it was."""
    m = ran["model"]
    assert (m["earlyStored"], m["earlyReplySeen"], m["earlyOutcome"]) == (True, True, "replied")
    assert (m["lateStored"], m["lateReplySeen"], m["lateOutcome"]) == (True, False, "reply dropped")
    assert (m["keepaliveStored"], m["keepaliveReplySeen"], m["keepaliveOutcome"]) == (True, False, "reply dropped")
    assert (m["plainStored"], m["plainReplySeen"], m["plainOutcome"]) == (False, False, "aborted")
    assert m["timerOfAGonePageFired"] is False
    assert m["pageDiedAt"] == m["commitMs"], "the old page does not run until the new document commits"
    assert m["stay"] == {"dead": False, "leaving": False, "blockedNavs": 1, "pages": 1}, m["stay"]
    cap = m["keepaliveCap"]
    assert (cap["keepaliveBig"], cap["plainBig"], cap["keepaliveSmall"]) == ("Failed to fetch", "sent", "sent"), cap
    assert cap["stored"] == ["ka-small", "plain-big"], "a keepalive request over 64 KiB reached the server (or a plain one did not): %r" % cap
    # the limit is ONE budget for the keepalive bodies in flight, and the size is counted in bytes
    b = m["sharedBudget"]
    assert (b["first"], b["second"], b["plain"], b["wide"], b["afterReply"]) == (
        "sent", "Failed to fetch", "sent", "Failed to fetch", "sent"), b
    assert b["wideChars"] < 64 * 1024 < b["wideBytes"], "the wide body must be under the cap as characters and over it as bytes: %r" % b
    assert b["heldAfterReplies"] == 0 and b["stored"] == ["b1", "b3", "b5"], b
    # a request the server is slow over finishes after one sent later
    s = m["slowRequest"]
    assert s["doneAt"]["s1"] - s["doneAt"]["s2"] == 500 and s["outcomes"] == ["replied", "replied"], s


def test_the_server_model_is_the_route_contract_of_the_backend(ran):
    """The behaviours the fix leans on, as backend/main.py and backend/drafts.py have them: a save keeps the
    server-owned keys the row has (so a page can never undo a filing by sending is_test), a FIRST save is inserted as
    sent (so a blob that says is_test creates the row filed, or filed as real), a save of a row that has never said
    seeds the key, and filing a project that has no row answers 200 with {"ok": true, "existed": false}."""
    m = ran["model"]
    assert m["serverOwnedKeys"] == list(drafts._SERVER_OWNED_KEYS)
    assert m["savingKeepsServerOwnedKeys"] == {"is_test": True, "archived": False, "assigned_estimator": "kyle@x.test",
                                               "project_name": "B"}
    first = m["firstSaveIsInsertedAsSent"]
    assert (first["seeded"]["bornIsTest"], first["seeded"]["is_test"]) == (True, True)
    assert (first["seededReal"]["bornIsTest"], first["seededReal"]["is_test"]) == (False, False)
    assert (first["plain"]["bornIsTest"], first["plain"]["is_test"]) == (None, None)
    assert m["aSaveSeedsAKeyTheRowNeverHad"]["is_test"] is True
    assert m["fileMissingRow"] == {"ok": True, "existed": False, "is_test": True}


@pytest.fixture()
def store(fake_supabase, monkeypatch):
    """The real routes over the in-memory fake (conftest), never the live client: see test_projects_test_flag.py."""
    st = {"drafts": [], "events": []}
    monkeypatch.setattr(drafts, "get_client", lambda: fake_supabase(st))
    return st


def test_the_model_answers_like_the_real_routes(ran, store):
    """The same requests, sent to backend/main.py's real routes (over the in-memory store) and to the model: a read of a
    project nobody saved, the first save, a read of what was saved, filing it, filing a project that is not there, and a
    first save that says is_test with a read of what it stored. Status codes agree, the filing answers are equal, a save
    answers the same keys, and what the model's read hands back is a subset of the real one's (the pages read `data` and
    `updated_at`). A model of a server that answered differently from the server would prove the fix against a server
    that is not there."""
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
    r = client.put("/api/draft/m3", json={"data": {"project_name": "A", "is_test": True}})
    real["putSeeded"] = {"status": r.status_code, "keys": sorted(r.json())}
    r = client.get("/api/draft/m3")
    real["getSeeded"] = {"status": r.status_code, "body": r.json()}

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
    assert got["putSeeded"]["status"] == real["putSeeded"]["status"] == 200
    assert got["putSeeded"]["keys"] == real["putSeeded"]["keys"]
    assert got["getSeeded"]["body"]["data"] == real["getSeeded"]["body"]["data"] == {"project_name": "A", "is_test": True}


def test_the_real_routes_create_a_row_filed_and_never_let_a_stale_blob_undo_a_filing(store):
    """THE TWO RULES THE SEED LEANS ON, on the REAL routes (the model above is held to these). Nothing here is the model.

      * A first save is inserted as sent: a blob that says is_test true creates the row filed as a test, one that says
        false creates it filed as a real bid, and one that says nothing creates it unfiled.
      * On an update the STORED value of a server-owned key wins over the blob's whenever the row has one, so a tab whose
        blob still says is_test true cannot put back a project somebody has since filed as real; a row that has never said
        takes the blob's word (the blob may seed a key the row has never had).

    Round 1 kept the flag out of the blob for fear of exactly the stale tab; keep_server_owned is what makes the blob a safe
    place for it (and test_projects_test_flag.py breaks that line and requires a red)."""
    def put(id_, data):
        r = client.put("/api/draft/" + id_, json={"data": data})
        assert r.status_code == 200 and r.json()["ok"] is True, r.json()

    def stored(id_):
        return client.get("/api/draft/" + id_).json()["data"]

    put("born-test", {"project_name": "A", "is_test": True})
    put("born-real", {"project_name": "A", "is_test": False})
    put("born-silent", {"project_name": "A"})
    assert stored("born-test")["is_test"] is True
    assert stored("born-real")["is_test"] is False
    assert "is_test" not in stored("born-silent")

    # a human files the test project as a REAL bid; the tab that started it goes on saving a blob that says test
    assert client.post("/api/draft/born-test/test", json={"is_test": False}).json()["is_test"] is False
    put("born-test", {"project_name": "A (edited)", "is_test": True})
    assert stored("born-test") == {"project_name": "A (edited)", "is_test": False}, "a stale blob undid a human's filing"

    # the other direction: a project somebody filed as a test is not put back among the real bids by a blob that says real
    put("born-real", {"project_name": "B"})
    client.post("/api/draft/born-real/test", json={"is_test": True})
    put("born-real", {"project_name": "B2", "is_test": False})
    assert stored("born-real")["is_test"] is True

    # a row that has never said takes the blob's word
    put("born-silent", {"project_name": "A", "is_test": True})
    assert stored("born-silent")["is_test"] is True


def test_the_board_opens_the_intake_the_way_the_harness_does():
    """The harness RUNS js/v2-board.js startNew() (world.startNewEstimate lifts it out of the file; it used to copy what it does),
    so it cannot walk a flow the board no longer starts. This is the board's shape the rest of the file leans on: it clears the
    three keys that make shared.js mint a fresh draft, leaves { audience: "GC" } behind on the GC tab, and opens /polish-intake.html
    with no ?d=."""
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


def test_the_projects_page_hands_the_live_intake_the_tab_it_started_from(ran):
    """The harness runs the REAL click handler of js/projects.js (lifted out of the file) and then the live intake's
    own shared.js: "+ New project" on Test leaves "1" under the new project's own key, on Active "0", and on All nothing, and
    the live intake opens on that very project (the id the click minted). The v1 flows below start from exactly this."""
    v1 = ran["v1"]
    assert v1["test"]["startOnArrival"] == "1", "Test: %r" % v1["test"]["startOnArrival"]
    assert v1["active"]["startOnArrival"] == "0", "Active: %r" % v1["active"]["startOnArrival"]
    assert v1["all"]["startOnArrival"] is None, "All: %r" % v1["all"]["startOnArrival"]


# ══ S1: the seed. A new project is born filed, whichever way it leaves ══════════════════════════════════
def test_a_new_project_is_born_filed_whichever_way_it_leaves(ran):
    """THE DEFECT, and the audit's F1. Continue at 100 ms (nothing saved yet), at 700 ms (the 600 ms autosave has run and
    the 2.5 s timer that sends it is armed) and at 3.3 s (the path that always worked), the GC tab's New (which starts
    the bid with something in it), Continue pressed twice 60 ms apart, Continue pressed while the 2.5 s autosave PUT is in
    flight, and typing that goes on while that PUT is in flight so that two saves overlap: in every one the row is CREATED
    filed under Test, nothing filed it afterwards, one row exists, and the estimate page is on it and says so.

    Red on round 1: every one of these rows is born unfiled and filed by a second request, which is how a double press or a
    press in the middle of a save leaves the estimate page a window in which to fork it."""
    flows = {
        "fast": ran["fast"], "fastAfterAutosave": ran["fastAfterAutosave"], "slow": ran["slow"], "gcTab": ran["gcTab"],
        "doublePress at 100": ran["doublePress"]["fast"], "doublePress at 700": ran["doublePress"]["afterAutosave"],
        "pressDuringAutosave": ran["pressDuringAutosave"], "overlappingSaves": ran["overlappingSaves"],
    }
    for name, r in flows.items():
        assert_filed_and_edited_directly(r, name)
    # Not vacuous: the overlap runs really did have two saves in flight, and the last word was the newest edit.
    over = ran["overlappingSaves"]
    puts = [q for q in reqs(over, "PUT", over["id"], page="intake")]
    assert len(puts) >= 2 and puts[1]["at"] < puts[0]["repliedAt"], "the first save was already answered when the second went: %r" % puts
    assert over["xData"]["address"] == "200 Main St", over["xData"]
    dbl = ran["doublePress"]["fast"]
    assert [p["accepted"] for p in dbl["presses"]] == [True, False] and len(dbl["navs"]) == 1, dbl["presses"]


def test_a_gc_tab_bid_is_saved_and_filed_as_the_intake_opens(ran):
    """The GC tab starts the bid with { audience: "GC" } already in the draft, so the sandbox has something to save as the intake
    opens and saves it, filed as a test: its row is on the server before anything is typed. A new estimate with nothing in it
    saves nothing (opening the beta must not create a project)."""
    gc, plain = ran["gcTab"], ran["fast"]
    assert gc["rowAtOpen"] is not None and gc["rowAtOpen"]["bornIsTest"] is True and gc["rowAtOpen"]["is_test"] is True, gc["rowAtOpen"]
    assert plain["rowAtOpen"] is None, "opening the intake on a project with nothing in it created a row: %r" % plain["rowAtOpen"]


def test_the_first_save_says_what_the_project_was_started_as(ran):
    """WHY it works, on the wire. The project's FIRST PUT (the autosave's, Continue's, the pagehide keepalive's, the estimate
    page's, whichever goes first) carries is_test in its body: true for a project started as a test, false for one started
    from the Active tab, and nothing for All. And the start is used up by that first write, so nothing is left armed in the
    one localStorage slot to file some other project (or this one, later) by mistake."""
    for flow in ("fast", "fastAfterAutosave", "slow"):
        r = ran[flow]
        first = reqs(r, "PUT", r["id"])[0]
        assert first["sentIsTest"] is True, "%s: the first save did not say the project is a test: %r" % (flow, first)
        assert r["starts"] == {}, "%s: a start was left armed by the first write (%r)" % (flow, r["starts"])
    v1 = ran["v1"]
    assert reqs(v1["test"], "PUT", v1["test"]["id"])[0]["sentIsTest"] is True
    assert reqs(v1["active"], "PUT", v1["active"]["id"])[0]["sentIsTest"] is False
    assert reqs(v1["all"], "PUT", v1["all"]["id"])[0]["sentIsTest"] is None


def test_the_start_is_said_by_the_first_write_that_has_content_and_only_for_its_own_project(ran):
    """shared.js's stamp, executed on its own. A start for THIS project is said in the blob by the first write that holds
    anything: true for a test, false for a real bid. A write that holds nothing yet (an empty partial on a project nobody has
    typed into) says nothing, so an untouched project stays a blob with nothing in it and never becomes a row. A blob that already
    says is_test (a human's word, written by a hydrate) is not overruled. A start for ANOTHER project is under that project's own
    key: not read here and not touched here. The one slot of an earlier version is read by nothing, whatever it holds. The stamp
    SPENDS nothing (the start is spent by a stored save: the next test), so every later write of the project says it too."""
    s = ran["stampRules"]
    armed = lambda k, v: s[k]["starts"] == {s[k]["id"]: v}
    assert s["test"]["blob"].get("is_test") is True and armed("test", "1"), s["test"]
    assert s["real"]["blob"].get("is_test") is False and armed("real", "0"), s["real"]
    assert "is_test" not in s["empty"]["blob"] and armed("empty", "1"), s["empty"]
    assert set(s["empty"]["blob"]) <= {"__draft_id"}, "an empty write made the project non-empty: %r" % s["empty"]["blob"]
    assert s["emptyThenContent"]["blob"].get("is_test") is True and armed("emptyThenContent", "1"), s["emptyThenContent"]
    assert s["says"]["blob"].get("is_test") is False and armed("says", "1"), s["says"]
    assert "is_test" not in s["other"]["blob"] and s["other"]["starts"] == {"someone-else": "1"}, s["other"]
    assert "is_test" not in s["legacyBare"]["blob"] and s["legacyBare"]["bare"] == "1", s["legacyBare"]
    assert "is_test" not in s["legacyBound"]["blob"] and s["legacyBound"]["bare"] == s["legacyBound"]["id"] + ":1", s["legacyBound"]
    assert s["later"]["blob"].get("is_test") is True and s["later"]["blob"]["project_name"] == "B" and armed("later", "1"), s["later"]


def test_a_start_is_spent_when_the_server_has_stored_a_copy_that_carries_it_and_not_before(ran):
    """The audit's F3 asked what happens to a start when something happens to the blob that carries it. Another tab's New project WIPES
    the shared blob, and a start that a write had spent went with it: the page's next write (Continue, on a blob that was empty) said
    nothing, and the project was created unsaid. So a write only SAYS the start, and the start is spent when the server stores a copy
    that carries it: the blob that held it can be wiped, and the next write says it again (and the page's queued copy still carries it).
    A save the server refuses spends nothing, and the next one carries it again. A v2 page's own word is spent the same way."""
    s = ran["stampRules"]
    keep = s["stampKeepsTheStart"]
    assert keep["blob"].get("is_test") is True and keep["starts"] == {keep["id"]: "1"}, "a write spent the start: %r" % keep
    again = s["saidAgainAfterAWipe"]
    assert again["blob"].get("is_test") is True and again["blob"]["project_name"] == "B" and again["starts"] == {again["id"]: "1"}, (
        "after the shared blob was wiped, the next write did not say what the project was started as: %r" % again)
    spent = s["spentOnceStored"]
    assert spent["starts"] == {} and spent["puts"] == [True], "a stored save did not spend the start, or did not carry it: %r" % spent
    refused = s["refusedSpendsNothing"]
    assert refused["starts"] == {refused["id"]: "0"} and refused["puts"] == [False], "a refused save spent the start: %r" % refused
    taken = s["takenSpends"]
    assert taken["starts"] == {} and taken["puts"] == [False, False], "the save after a refused one lost the start: %r" % taken
    kept = s["markKeptAfterSaying"]
    assert kept["blob"].get("is_test") is True, kept
    wiped = s["markSaidAgainAfterAWipe"]
    assert wiped["blob"].get("is_test") is True and wiped["blob"]["project_name"] == "B", (
        "a v2 page's own word was spent by the write that said it, and a wiped blob lost it: %r" % wiped)
    done = s["markSpentOnceStored"]
    assert "is_test" not in done["blob"] and done["blob"]["project_name"] == "C", "a v2 page's own word outlived the save that stored it: %r" % done


def test_a_v2_pages_own_word_is_said_by_the_first_write_it_makes_and_only_by_that(ran):
    """The other source of a start: a v2 page's sandbox found no row for the project, which makes it a test (TW.startsAsTest).
    Held in this page's memory, it is said by the first write that holds anything, over the Active tab's start (whatever a v2
    page writes is a test) and never over a word the blob already holds; a write with nothing in it does not say it; and a word
    for ANOTHER project is not said here. (It is spent by a stored save, like any start: the test above.)"""
    s = ran["stampRules"]
    assert s["mark"]["blob"].get("is_test") is True and s["mark"]["starts"] == {}, s["mark"]
    assert s["markOverReal"]["blob"].get("is_test") is True and s["markOverReal"]["starts"] == {s["markOverReal"]["id"]: "0"}, s["markOverReal"]
    assert "is_test" not in s["markEmpty"]["blob"] and set(s["markEmpty"]["blob"]) <= {"__draft_id"}, s["markEmpty"]
    assert s["markEmptyThenContent"]["blob"].get("is_test") is True, s["markEmptyThenContent"]
    assert s["markSaysFalse"]["blob"].get("is_test") is False, s["markSaysFalse"]
    assert "is_test" not in s["markOther"]["blob"], s["markOther"]


def test_new_project_mints_the_projects_id_with_its_own_start(ran):
    """What "+ New project" leaves, on shared.js's own function: a position (the Test tab, the Active tab) mints the new project's
    id as the browser's current draft and puts "1" or "0" under THAT id's key, so a second New project leaves the first one's
    start where it was; All and Inactive say nothing (no id, no start). The one slot of an earlier version is removed by every one
    of them."""
    s = ran["stampRules"]
    t, r, n = s["newTest"], s["newReal"], s["newSaidNothing"]
    assert t["bare"] is None and r["bare"] is None and n["bare"] is None, (
        "the earlier version's slot was left behind: %r" % [t["bare"], r["bare"], n["bare"]])
    assert t["draftId"] and t["draftId"] != t["before"] and t["starts"] == {t["draftId"]: "1"}, t
    assert r["draftId"] != t["draftId"] and r["starts"] == {t["draftId"]: "1", r["draftId"]: "0"}, (
        "the second New project touched the first one's start: %r" % r["starts"])
    assert n["draftId"] == r["draftId"] and n["starts"] == r["starts"], "All said something: %r" % n


def test_a_blob_with_nothing_in_it_is_sent_as_it_is(ran):
    """putDraft puts a start on a blob that has content and never on one that holds nothing but the stamp, and does not spend the
    start on it: an untouched project must not become a row that says it is a test."""
    e = ran["stampRules"]["emptyPut"]
    assert e["puts"] == [None], "the start was put on a copy with nothing in it: %r" % e["puts"]
    assert e["starts"] == {e["id"]: "1"}, "the start was spent on a copy with nothing in it: %r" % e["starts"]


def test_every_other_door_out_of_the_intake_leaves_one_row_born_filed(ran):
    """The audit's F2. The "2 · Estimate" step link, Back (to the Projects page), a closed tab and a reload, at 0.1, 0.6, 0.7,
    1.5, 3.0, 3.1 and 3.2 s after the last edit (before the page's own 600 ms save, between it and the 2.5 s timer that sends
    it, and across the moment the autosave PUT goes). None of them waits for anything, so each sends whatever it sends as the
    page goes (a plain request that dies with the page, or a keepalive one whose reply nobody sees).

    Whatever reached the server was born FILED: no row is ever on the board unfiled, nothing is forked, and there is
    never a second row. Where the estimator went to the estimate page it is on the project, editing it directly; where
    they did not (Back, a closed tab) the project is reopened a minute later in the v2 intake and is filed, directly
    editable and still the only row, whether the first leg left a row (a keepalive PUT) or none (a plain one dropped).

    Not vacuous: all four doors at all seven times, and every one of them that did not go to the estimate page leaves a row, the
    first PUT included at 100 ms (inside the intake's own 600 ms debounce, where round 2 left none: F5)."""
    exits = ran["exits"]
    assert len(exits) == 28 and {(e["door"], e["waitMs"]) for e in exits} == {
        (d, w) for d in ("link", "back", "close", "reload") for w in (100, 600, 700, 1500, 3000, 3100, 3200)}
    left_a_row = 0
    for r in exits:
        flow = "%s at %d ms" % (r["door"], r["waitMs"])
        assert_born_filed(r, flow)
        if r["door"] == "link":
            est = r["estimate"] or {}
            assert est.get("settled") is True and est.get("draftId") == r["id"] and DIRECT in says(r) and COPY not in says(r), (
                "%s: %s" % (flow, describe(r)))
            continue
        before = r["before"]
        assert before["x"] is not None, "%s: the page left and no row was saved: %r" % (flow, before)
        left_a_row += 1
        assert before["x"]["bornIsTest"] is True and before["x"]["is_test"] is True, (
            "%s: the row the closed tab left behind was unfiled: %r" % (flow, before["x"]))
        assert before["beta"] is None
        assert r["intakeDraft"] == r["id"] and DIRECT in r["intakeNote"] and COPY not in r["intakeNote"], (
            "%s: the reopened project is not edited directly: %r %r" % (flow, r["intakeDraft"], r["intakeNote"]))
    assert left_a_row == 21, left_a_row


def test_the_next_new_estimate_does_not_leave_the_first_one_behind(ran):
    """F2 in the audit's own words: the first project is left by a closed tab 700 ms after the last edit, and the NEXT new
    estimate then overwrites the one localStorage slot that round 1 kept the filing in, so nothing could ever heal the
    first. It was born filed, so there is nothing to heal. (And the second, started and left in its turn, is filed too.)"""
    r = ran["overtaken"]
    assert r["x"] is not None and r["x"]["bornIsTest"] is True and r["x"]["is_test"] is True and r["x"]["flips"] == 0, r["x"]
    second = r["second"]
    assert second is None or (second["bornIsTest"] is True and second["is_test"] is True), second
    assert [i for i in r["rowIds"] if i.endswith("-beta")] == [], r["rowIds"]


def test_whatever_the_latencies_the_new_project_is_born_filed_and_never_forked(ran):
    """Sixteen runs: a slow save, a slow /test (which nothing sends any more), both, a slow link, a next page that boots at
    once or late, and everything fast, each with Continue at 100 ms and at 700 ms. On 59922bd the answer depended on who
    was faster; it must not."""
    sweep = ran["sweep"]
    assert len(sweep) == 16 and len({s["combo"] for s in sweep}) == 8
    bad = []
    for s in sweep:
        x = s["x"]
        ok = (x is not None and x["bornIsTest"] is True and x["is_test"] is True and x["flips"] == 0 and s["beta"] is None
              and s["estimateDraft"] == s["id"] and DIRECT in (s["note"] or ""))
        if not ok:
            bad.append("%s, Continue at %d ms: project %s, copy %s" % (s["combo"], s["waitMs"], x, s["beta"]))
    assert not bad, "not born filed and edited directly:\n  " + "\n  ".join(bad)


def test_a_stale_tab_cannot_undo_a_humans_filing(ran):
    """The shape round 1 kept the flag out of the blob to avoid, now that the blob carries it: somebody files the new
    project as a REAL bid after it was born filed, while the estimator's tab still holds a blob that says is_test true and
    goes on saving. The tab's blob does say true, its next save does carry it, and the row stays what the human made it
    (the server keeps what the row has: drafts.save_draft keep_server_owned, which the real routes are held to above)."""
    r = ran["staleTab"]
    assert r["x"] is not None and r["x"]["bornIsTest"] is True, r["x"]
    assert r["filedReal"]["is_test"] is False and r["x"]["is_test"] is False and r["x"]["flips"] == 1, (r["filedReal"], r["x"])
    assert r["blobFlag"] is True, "the tab's blob does not carry the flag, so this run does not test what it says"
    last = reqs(r, "PUT", r["id"])[-1]
    assert last["sentIsTest"] is True and last["outcome"] == "replied", "the stale tab's save did not go out carrying the flag: %r" % last


# ── Continue is never trapped ────────────────────────────────────────────────────────────────────────────
def test_a_server_that_never_answers_does_not_trap_the_estimator(ran):
    """Waiting for the save is bounded. The first PUT is never answered, and the estimator is on the estimate page
    within ten seconds of pressing Continue (the bound is SAVE_WAIT_MS in polish-intake.js), where the sandbox saves the
    project it finds unsaved, already filed. Without a bound Continue would sit there until the browser gave up."""
    r = ran["feedback"]["hung"]
    assert len(r["navs"]) == 1, "Continue never left the intake: %r" % r["navs"]
    assert r["navs"][0]["askedAt"] - r["continueAt"] <= 10000, r["navs"][0]
    assert r["navs"][0]["askedAt"] - r["continueAt"] >= 7000, "Continue did not wait for the save at all: %r" % r["navs"][0]
    assert r["estimate"] and r["estimate"]["settled"] is True, r["estimate"]
    assert_filed_and_edited_directly(r, "the first save was never answered")
    assert r["blob"].get("is_test") is True, "the project's own blob does not say it is a test: %r" % r["blob"]


def test_continue_saves_a_draft_too_big_for_a_keepalive_request_before_it_leaves(ran):
    """WHAT CONTINUE'S WAIT STILL GUARDS, now that it is no longer what files a new project. A saved project whose draft is over
    64 KiB (a real bid has measured about 89 KB; see shared.js putDraft) cannot be sent as the page goes: the browser refuses a
    keepalive request that big on the spot and nothing is sent. Before Continue waited, the last edits made on the intake
    reached the server only when the estimate page's own autosave went, and the server held the stale draft until then.
    Waiting sends the save as a plain request, answered to a page that is still there, before the browser leaves."""
    r = ran["bigDraft"]
    assert DIRECT in r["noteOnOpen"], "the run does not start from a saved test project: %r" % r["noteOnOpen"]
    first = reqs(r, "PUT", "big-4", page="intake")[0]
    assert (first["keepalive"], first["outcome"]) == (False, "replied"), first
    assert r["address"] == "9 Big Address", (
        "the last edit made on the intake never reached the server (the save that went as the page left was refused): %r" % r["address"])


def test_a_save_that_fails_at_once_is_not_waited_out(ran):
    """No network: the first PUT fails immediately. Continue goes on at once (the local copy is safe, and the estimate page
    saves what it finds unsaved), it does not sit out the bound, and the project still ends born filed."""
    r = ran["saveFaults"]["once_network"]
    assert len(r["navs"]) == 1 and r["navs"][0]["askedAt"] - r["continueAt"] < 1000, r["navs"]
    assert_filed_and_edited_directly(r, "no network for the first save")
    assert r["blob"].get("is_test") is True, "the project's own blob does not say it is a test: %r" % r["blob"]


# ══ S2: a filing the server will not do ═════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("mode", ["http500", "okfalse", "network", "hang", "html", "gone"])
def test_nothing_depends_on_a_filing_request(ran, mode):
    """The audit's F3 and F4's cause. /test fails six ways (HTTP 500, a 200 carrying {"ok": false}, no network, no answer at
    all, a 200 that is not JSON, a 200 that says the row is not there), under Continue at 100 ms and under the step link at
    700 ms. On round 1 a failure was never read, the intent was already erased, and the estimate page forked a copy of the
    estimator's own project and told them the real one was "untouched in Active"; a /test nobody answered stopped the next
    page from loading. A project that is born filed needs no /test, so none of it can happen: the same end state as a
    server where /test works, and no /test is sent for it at all."""
    for flow, r in (("Continue", ran["filingFaults"]["continue"][mode]), ("the step link", ran["filingFaults"]["link"][mode])):
        assert_filed_and_edited_directly(r, "%s with /test %s" % (flow, mode))
        assert reqs(r, "TEST", r["id"]) == [], "%s: a /test was sent for the project: %r" % (flow, reqs(r, "TEST", r["id"]))
    assert len(ran["filingFaults"]["continue"][mode]["navs"]) == 1
    c = ran["filingFaults"]["continue"][mode]
    assert c["navs"][0]["askedAt"] - c["continueAt"] < 1000, "Continue waited on something: %r" % c["navs"]


@pytest.mark.parametrize("mode", ["http500", "okfalse", "network"])
def test_a_save_that_fails_once_still_ends_born_filed(ran, mode):
    """The first save fails once (HTTP 500, a 200 carrying {"ok": false}, no network). Continue leaves; the estimate page finds
    nothing saved and saves the project itself. The flag is in the project's own blob, so the retry carries it: born
    filed, edited directly, one row."""
    r = ran["saveFaults"]["once_" + mode]
    assert_filed_and_edited_directly(r, "the first save failed once (%s)" % mode)
    assert r["blob"].get("is_test") is True, "the project's own blob does not say it is a test: %r" % r["blob"]


@pytest.mark.parametrize("mode", ["http500", "okfalse", "network"])
def test_a_save_that_cannot_be_made_is_said_and_never_claimed_as_a_filing(ran, mode):
    """The server takes no save at all. The estimate page cannot save the new project, and it must not claim it is filed:
    on round 1 it said "This project is filed as a test, so Estimating Tool v2 is editing it directly" over a project that was
    nowhere. It says the project has not been saved to the server yet and where it will land. Nothing exists on the server
    to mislabel; and when the server is back, the next save of the project carries its flag and creates it filed."""
    r = ran["saveFaults"]["down_" + mode]
    est = r["estimate"] or {}
    assert r["x"] is None and r["rowIds"] == [], "a row exists although no save was ever taken: %s" % describe(r)
    assert est.get("settled") is True and est.get("draftId") == r["id"], est
    assert UNSAVED in says(r) and DIRECT not in says(r) and COPY not in says(r), "the page claims more than it knows: %r" % says(r)
    assert "Test tab" in says(r), "the page does not say where the project will land: %r" % says(r)
    after = r["afterRecovery"]
    assert_born_filed(after, "the server came back (%s)" % mode)
    assert (after["estimate"] or {}).get("draftId") == r["id"], "the estimate page left the project: %s" % describe(after)


def test_a_new_project_that_could_not_be_saved_as_the_page_opened_is_still_created_filed(ran):
    """The GC tab starts the bid with something in the draft, so the sandbox saves it as the intake opens, and the server is
    down. The blob holds no flag of its own (nothing has been written through setState yet), so the sandbox arms the start
    again: the intake says so at once, and the first write after the server is back says "test" in its own blob and creates
    the project filed. Without that the project is created unfiled by the very save that rescued it."""
    r = ran["saveFaults"]["gcDown_http500"]
    assert UNSAVED in r["noteAtOpen"] and DIRECT not in r["noteAtOpen"], r["noteAtOpen"]
    assert r["x"] is None and r["rowIds"] == [], "a row exists although no save was ever taken: %s" % describe(r)
    assert_born_filed(r["afterRecovery"], "the server came back after the GC tab opened the intake")


# ══ S3: no page's boot waits on a filing ═══════════════════════════════════════════════════════════════
def test_the_next_page_boots_while_a_filing_never_answers(ran):
    """The audit's F4. The estimator leaves a new project 100 ms after its last edit, for ANOTHER project's estimate page.
    shared.js hydrates the other project and first flushes the blob it is evicting; round 1's putDraft waited for the filing
    that followed that flush, so a /test nobody answered stopped the other page from ever booting ("Loading this
    project..." for ever). The new project is saved by that flush, born filed, and the other page boots and shows the
    estimator its test copy, with a control run that has no fault and with /test failing outright."""
    runs = sorted(ran["bootWhileFilingHangs"].items())
    assert [name for name, _r in runs] == ["control", "hang", "http500"]
    for name, r in runs:                       # FIRST, and for every run: the other page boots (the fact round 1 broke)
        last = r["lastPage"]
        assert last["settled"] is True and last["loading"] == "", "%s: the other project's page never finished booting: %r" % (name, last)
        assert r["lastKind"] == "estimate" and r["lastDraft"] == "real-2-beta" and COPY in last["note"], (name, r["lastDraft"], last["note"])
    for name, r in runs:
        assert r["x"] is not None and r["x"]["bornIsTest"] is True and r["x"]["is_test"] is True and r["x"]["flips"] == 0, (name, r["x"])
        assert r["other"] == {"is_test": None, "bornIsTest": None, "flips": 0, "beta_sandbox_of": None, "project_name": "Overland Park Lab"}, (
            "%s: the other, real project was written to or filed: %r" % (name, r["other"]))
        assert reqs(r, "TEST", r["id"]) == [], name
        assert [q for q in reqs(r, id_="real-2") if q["method"] != "GET"] == [], "%s: the real project was written to" % name


# ══ S4: Continue's button ═══════════════════════════════════════════════════════════════════════════════
def test_continue_tells_the_estimator_it_is_saving(ran):
    """The audit's F5. While Continue waits for its save (up to eight seconds on a slow server) the button is disabled and
    says "Saving…"; it has its own label before, and the estimator who sees nothing happen is the one who presses again.
    A second press (a double click, Enter in a box) is not accepted, and one press is all the page is ever asked."""
    s = ran["feedback"]["saving"]
    assert s["labelAtOpen"].strip() and SAVING not in s["labelAtOpen"], (
        "the page has no Continue button to speak through (its label reads %r)" % s["labelAtOpen"])
    assert s["presses"][0]["accepted"] is True and s["presses"][0]["button"] == {"disabled": True, "label": SAVING}, s["presses"]
    assert s["samples"]["early"]["disabled"] is True and s["samples"]["early"]["label"] == SAVING, s["samples"]
    assert s["samples"]["late"]["disabled"] is True and s["samples"]["late"]["label"] == SAVING, s["samples"]
    assert len(s["navs"]) == 1
    twice = ran["feedback"]["pressedTwice"]
    assert [p["accepted"] for p in twice["presses"]] == [True, False, False], twice["presses"]
    assert len(twice["navs"]) == 1 and len(reqs(twice, "PUT", twice["id"], page="intake")) <= 2, (twice["navs"], reqs(twice, "PUT"))
    assert_filed_and_edited_directly(twice, "pressed three times")
    hung = ran["feedback"]["hung"]
    assert hung["samples"]["midway"]["disabled"] is True and hung["samples"]["midway"]["label"] == SAVING, hung["samples"]


def test_continue_gives_the_button_back_when_the_browser_does_not_go(ran):
    """The browser does not go (the load was stopped, a prompt was answered no): the page is still there, and the button
    it left disabled would be a dead end. It has its own label back, works again, and a second Continue asks the browser
    again. The same after a save that failed."""
    b = ran["feedback"]["blocked"]
    assert b["labelAtOpen"].strip(), "the page has no Continue button to give back"
    assert b["pageAlive"] is True and [n.get("blocked") for n in b["navs"][:1]] == [True], b["navs"]
    assert b["restored"] == {"disabled": False, "label": b["labelAtOpen"]}, b["restored"]
    assert b["pressedAgain"]["navs"] == 2 and b["pressedAgain"]["button"] == {"disabled": False, "label": b["labelAtOpen"]}, b["pressedAgain"]
    f = ran["feedback"]["failedSave"]
    assert f["restored"] == {"disabled": False, "label": f["labelAtOpen"]}, f["restored"]


def test_continue_says_it_is_saving_and_ignores_a_second_press_on_the_page_alone(intake):
    """The REAL onSubmit (tests/js/polish-intake-harness.js), with a save the test answers BY HAND. While the save is out
    the button is disabled and says "Saving…", the page's own bound is the only timer armed, and a second press neither
    saves nor flushes again. When the answer comes it says it is opening the estimate. Nothing has been sent to the estimate
    page before then."""
    c = intake["continueWaits"]
    assert c["labelBefore"]["disabled"] is False and c["labelBefore"]["label"].strip(), c["labelBefore"]
    w = c["whileWaiting"]
    assert (w["navigated"], w["savedFirst"], w["flushes"], w["armed"]) == (0, 1, 1, 1), w
    assert w["button"] == {"disabled": True, "label": SAVING}, w["button"]
    assert (w["flushesAfterASecondPress"], w["savesAfterASecondPress"]) == (1, 1), w
    assert c["afterAnswer"]["button"] == {"disabled": True, "label": OPENING}, c["afterAnswer"]


def test_continue_gives_the_button_back_on_the_page_alone(intake):
    """Once Continue has asked the browser to leave, the page keeps ONE timer (the browser may not go), and when it fires the
    button has its own label back and Continue works again. If the page throws before it asks (a draft it cannot read),
    the button is not left saying "Saving…": nothing was saved or asked of the browser, and it has its label back at once."""
    c = intake["continueWaits"]
    assert c["afterAnswer"]["navigated"] == ["/polish-estimate.html?d=proj-1"] and c["afterAnswer"]["armed"] == 1, c["afterAnswer"]
    assert c["afterGiveBack"] == {"armed": 0, "button": c["labelBefore"], "navigated": 1}, c["afterGiveBack"]
    assert c["pressedAgain"]["navigated"] == 2 and c["pressedAgain"]["button"] == {"disabled": True, "label": OPENING}, c["pressedAgain"]
    t = c["threwBefore"]
    assert t["error"] == "cannot read the form" and t["navigated"] == 0 and t["flushes"] == 0 and t["armed"] == 0, t
    assert t["button"] == c["labelBefore"], t["button"]


def test_continue_leaves_when_the_wait_is_over_however_it_ends(intake):
    """Four endings the real flushState or the clock can produce. A save nobody answers is let go by the page's own
    bound (and not before it, with the button saying so all the while); a save that failed (flushState answers false) and a
    save that threw (it never does, so this is the page's own `catch`, which no other test reaches) both leave at once;
    and in all of them the wait's own timer is cleared (the one timer left is the give-back timer)."""
    c = intake["continueWaits"]
    n = c["neverAnswered"]
    assert n["beforeBound"] == 0 and n["afterBound"] == ["/polish-estimate.html?d=proj-1"] and n["armedAfter"] == 1, n
    assert n["buttonBeforeBound"] == {"disabled": True, "label": SAVING}, n["buttonBeforeBound"]
    assert c["failedSave"]["navigated"] == ["/polish-estimate.html?d=proj-1"] and c["failedSave"]["armedAfter"] == 1, c["failedSave"]
    assert c["threw"] == {"navigated": ["/polish-estimate.html?d=proj-1"], "armedAfter": 1, "saved": True}, c["threw"]


# ══ S5: a stale start ═══════════════════════════════════════════════════════════════════════════════════
def test_a_stale_start_for_a_project_that_has_moved_on_is_copied_and_never_filed(ran):
    """The audit's F6. A pending start for a project that has been worked on and SENT since (it has files and a sent
    proposal, and nobody ever said whether it is a test) is a real bid like any other to the estimate page: it is copied
    as it always was, the copy is filed, and the real row is only ever READ. On round 1 the net filed it and then said "No real
    bid is involved" over a bid that had been sent."""
    r = ran["staleStart"]
    assert r["x"] == {"is_test": None, "bornIsTest": None, "flips": 0, "beta_sandbox_of": None, "project_name": "Wichita Warehouse"}, r["x"]
    assert [q for q in reqs(r, id_=REAL_PROJECT) if q["method"] != "GET"] == [], "the stale start's project was written to or filed"
    assert r["beta"] is not None and r["beta"]["is_test"] is True and r["beta"]["beta_sandbox_of"] == REAL_PROJECT, r["beta"]
    assert r["beta"]["bornIsTest"] is True, r["beta"]
    est = r["estimate"] or {}
    assert est.get("draftId") == REAL_PROJECT + "-beta" and COPY in says(r) and DIRECT not in says(r) and "No real bid" not in says(r), describe(r)


# ══ S6: the record of what the server holds ═════════════════════════════════════════════════════════════
def test_the_record_of_what_the_server_holds_is_written_as_the_first_save_is_stored(ran):
    """The audit's F7. The browser remembers a digest of the copy the server last stored (SYNCED_KEY), which is what the Files
    page reads to tell a copy that is ahead of the server from one that is behind it. The first save of a new project
    records it the moment it is stored, so that a Continue that waits for the save leaves with the record written, and the
    flag the save carries does not move the digest (is_test is not part of it, and a copy that said so would read as changed
    on every project started as a test)."""
    r = ran["synced"]
    assert r["synced"] == r["id"] + ":" + r["digestNow"] and r["digestNow"], (r["synced"], r["digestNow"])
    assert r["navs"][0]["syncedAtAsk"] == r["synced"], "Continue asked to leave before the record was written: %r" % r["navs"][0]
    assert r["blob"].get("is_test") is True and r["x"]["bornIsTest"] is True, (
        "the project's own blob does not say it is a test, or its row was created unfiled: %r %r" % (r["blob"].get("is_test"), r["x"]))


# ══ S7: the live intake, through the Projects page ══════════════════════════════════════════════════════
def test_a_project_started_from_the_test_tab_is_born_filed_through_the_live_intake(ran):
    """The live intake's Continue does setState and location.assign in one breath, so its first PUT leaves through the
    pagehide handler and its reply is never seen: on round 1 a project started from the Projects page's Test tab sat in
    Active, unfiled, until some later page's save was answered (the Estimate step's own autosave, about three seconds on, and
    if the estimator closed that tab first, until another one was). Born filed now, on the page that is leaving, and still
    filed when the Estimate step's tab is closed straight away."""
    for name in ("test", "testClosed"):
        r = ran["v1"][name]
        assert r["x"] is not None and r["x"]["bornIsTest"] is True and r["x"]["is_test"] is True and r["x"]["flips"] == 0, (name, r["x"])
        assert r["rowIds"] == [r["id"]], (name, r["rowIds"])
    r = ran["v1"]["testClosed"]
    onward = [n for n in r["navs"] if "/estimate-review.html" in n["to"]]
    assert r["nextPage"] is not None and len(onward) == 1 and onward[0]["to"].endswith("?d=" + r["id"]), r["navs"]
    assert [n["to"] for n in r["navs"]][-1].endswith("/blank.html"), "the run does not close the Estimate step's tab: %r" % r["navs"]


def test_a_project_started_from_the_active_tab_is_born_as_a_real_bid(ran):
    """"Active writes false rather than nothing on purpose": absent lets the name heuristic vote, and a real bid for a customer
    with "test" in the name would file itself away. False is somebody saying it IS a real bid. The project is created saying
    so, on the first save, however the live intake is left."""
    for name in ("active", "activeClosed"):
        r = ran["v1"][name]
        assert r["x"] is not None and r["x"]["bornIsTest"] is False and r["x"]["is_test"] is False and r["x"]["flips"] == 0, (name, r["x"])


def test_all_and_inactive_start_a_project_that_nobody_has_said_anything_about(ran):
    """Neither tab is a statement about test-ness, so neither forces one: the project is created with no is_test at all, as it
    always was, and the Projects page's name heuristic keeps its vote."""
    for name in ("all", "allClosed"):
        r = ran["v1"][name]
        assert r["x"] is not None and r["x"]["bornIsTest"] is None and r["x"]["is_test"] is None and r["x"]["flips"] == 0, (name, r["x"])
        assert reqs(r, "TEST") == [], name


# ══ projects that are not a new test project of this browser's ══════════════════════════════════════════
REAL_PROJECT = "proj-9"


def test_a_real_bid_saved_in_the_live_intake_is_never_flagged(ran):
    """A real spreadsheet bid opened in the live intake from the Projects page (the real shared.js hydrates it, the real
    index.js saves it), its address changed and Continue pressed, with something else in this browser: nothing at all;
    ANOTHER project's start (which is neither applied to this one nor used up); and the start of a "+ New project" pressed on the
    Test tab and abandoned for this bid (the real click, then the bid opened from the new project's page: its start is under
    ITS key, which this bid can never read). The bid is saved, as itself: no is_test in what was sent, none on the row, no
    filing request, and the one row there is."""
    for name in ("clean", "anotherStart", "abandonedNew"):
        r = ran["v1Real"][name]
        starts = {"clean": {}, "anotherStart": {"other-1": "1"}, "abandonedNew": {r["abandoned"]: "1"}}[name]
        assert r["x"] == {"is_test": None, "bornIsTest": None, "flips": 0, "beta_sandbox_of": None,
                          "project_name": "Nearman Creek Epoxy"}, (name, r["x"])
        assert r["address"] == "9 New Address" and r["draftOnIntake"] == "sheet-3", "%s: the bid was not saved as itself: %r" % (name, r["address"])
        puts = reqs(r, "PUT", "sheet-3")
        assert puts and [p["sentIsTest"] for p in puts] == [None] * len(puts), "%s: a save said is_test: %r" % (name, puts)
        assert reqs(r, "TEST") == [] and r["rowIds"] == ["sheet-3"], (name, r["rowIds"])
        assert r["starts"] == starts and r["startsBeforeContinue"] == starts, (
            "%s: the starts this browser holds are %r, expected %r" % (name, r["starts"], starts))


def test_a_real_project_is_copied_and_never_written_to_or_filed(ran):
    """The sandbox's whole job, through the intake: a real project opened in v2 is copied, the copy is filed, and
    the real row is only ever READ, through Continue and onto the estimate page."""
    r = ran["realThroughIntake"]
    assert r["real"] == {"is_test": None, "bornIsTest": None, "flips": 0, "beta_sandbox_of": None, "project_name": "Nearman Creek"}
    assert r["realAddress"] == "1 Water Works Dr", "the real project's row was written to"
    assert [q for q in reqs(r, id_="real-1") if q["method"] != "GET"] == [], "the real project was written to or filed"
    assert r["beta"] is not None and r["beta"]["is_test"] is True and r["beta"]["beta_sandbox_of"] == "real-1"
    assert r["beta"]["bornIsTest"] is True, "the copy was created unfiled: %r" % r["beta"]
    assert r["beta"]["project_name"] == "Nearman Creek (beta test)"
    assert r["draftOnOpen"] == "real-1-beta" and COPY in r["noteOnOpen"]
    assert (r["estimate"] or {}).get("draftId") == "real-1-beta"


# (run, what the real row's is_test is, the starts this browser still holds at the end)
REAL_CASES = [
    ("realProject", None, {}),
    ("anotherProjects", None, {"other-1": "1"}),
    ("saidReal", False, {REAL_PROJECT: "1"}),
    ("filingAsReal", None, {REAL_PROJECT: "0"}),
]


def test_a_real_project_is_copied_never_filed_and_never_written_to(ran):
    """THE RULE NOTHING MAY BREAK. A project nobody here made as a new test project, whatever else is in storage, is a real
    bid: the sandbox copies it as it always did, files the copy, and never writes to the real row.
      realProject      nothing pending at all
      anotherProjects  ANOTHER project's start is pending: it is neither used nor lost
      saidReal         a human filed this one as a real bid (is_test false) and a start for it is still pending
      filingAsReal     the pending start says "real" ("0", the Active tab's New project), not "test"
    In every one the real row is read and nothing else: no save, no filing, and its is_test is what it was."""
    for scenario, is_test, pending in REAL_CASES:
        r = ran[scenario]
        assert r["x"] == {"is_test": is_test, "bornIsTest": is_test, "flips": 0, "beta_sandbox_of": None,
                          "project_name": "Wichita Warehouse"}, (scenario, r["x"])
        assert [q for q in reqs(r, id_=REAL_PROJECT) if q["method"] != "GET"] == [], (
            "%s: the real project was written to or filed" % scenario)
        assert r["beta"] is not None and r["beta"]["is_test"] is True and r["beta"]["beta_sandbox_of"] == REAL_PROJECT, (scenario, r["beta"])
        assert r["beta"]["bornIsTest"] is True, "%s: the copy was created unfiled: %r" % (scenario, r["beta"])
        assert r["beta"]["project_name"] == "Wichita Warehouse (beta test)", (scenario, r["beta"])
        est = r["estimate"] or {}
        assert est.get("draftId") == REAL_PROJECT + "-beta" and COPY in says(r) and DIRECT not in says(r), (
            "%s: %s" % (scenario, describe(r)))
        assert r["starts"] == pending, "%s: the pending start was used up or changed: %r, was %r" % (scenario, r["starts"], pending)


def test_a_copy_is_edited_directly_and_nothing_is_filed_for_it(ran):
    """A test copy whose own start is somehow pending (it never is: nothing writes one for a copy) is still what it
    always was to the sandbox: edited directly, with nothing sent for it."""
    r = ran["aCopy"]
    assert r["x"] == {"is_test": None, "bornIsTest": None, "flips": 0, "beta_sandbox_of": "some-real-project",
                      "project_name": "Wichita Warehouse (beta test)"}, r["x"]
    assert [q for q in reqs(r, id_=REAL_PROJECT) if q["method"] != "GET"] == [], "something was sent for a copy"
    assert (r["estimate"] or {}).get("draftId") == REAL_PROJECT and DIRECT in says(r), describe(r)
    assert r["starts"] == {REAL_PROJECT: "1"}


def test_no_flow_reloads_the_page_in_a_loop(ran):
    """Not a check of the fix, a check of the model's runs: shared.js hydrates a project and reloads, and anything
    that claims the one storage slot in between would have it do that for ever. Every run ends."""
    flows = [ran[k] for k in ("fast", "fastAfterAutosave", "slow", "gcTab", "pressDuringAutosave", "overlappingSaves",
                              "overtaken", "staleTab", "synced", "realThroughIntake", "realProject", "anotherProjects",
                              "saidReal", "filingAsReal", "staleStart")]
    flows += list(ran["doublePress"].values()) + ran["exits"] + ran["sweep"] + list(ran["bootWhileFilingHangs"].values())
    for group in ("continue", "link"):
        flows += list(ran["filingFaults"][group].values())
    flows += list(ran["saveFaults"].values()) + list(ran["feedback"].values()) + list(ran["v1"].values())
    assert [f for f in flows if f.get("runaway")] == []


def _sandbox_code():
    return (FRONTEND / "js" / "polish-sandbox.js").read_text(encoding="utf-8")


def test_the_model_spells_the_start_key_the_way_shared_js_does():
    """shared.js is the only file that names a project's start (the sandbox used to write one too, and no longer does: a v2 page
    says it to shared.js's memory). The model reads the starts under the same key, so a rename in one place is a red test here and
    not a start that is written where nothing reads it."""
    shared = (FRONTEND / "shared.js").read_text(encoding="utf-8")
    world = (TESTS / "js" / "_world.js").read_text(encoding="utf-8")
    keys = {
        "shared.js NEW_IS_TEST_KEY": re.search(r'const NEW_IS_TEST_KEY = "([^"]+)";', shared).group(1),
        "_world.js KEYS.intent": re.search(r'intent: "([^"]+)",', world).group(1),
    }
    assert len(set(keys.values())) == 1 and INTENT_KEY in keys.values(), keys
    assert 'function startKey(id) { return NEW_IS_TEST_KEY + ":" + id; }' in shared, "a project's start is no longer under its own key"
    assert "markNewProjectAsTest" not in _sandbox_code(), "the sandbox writes a start of its own again"


# ══ ROUND 3: a project's start is its own, and a look at a page starts nothing ══════════════════════════
# The audit of round 2 (F1 to F5). Round 2 kept what a project was STARTED as in ONE localStorage slot, and the slot could be
# overwritten by a page that only looked at a project (F1) or by another project's start (F3), and a blob that never went through
# setState could not carry it at all (F2). The runs are tests/js/new-estimate-test-flag-harness.js's `looks`, `abandonedBoardStart`,
# `twoTabs` and `bigDraftLeftEarly`, on the model's tabs (one localStorage, a sessionStorage per tab) and with the REAL starts:
# projects.js's "+ New project" click handler and portal.js's startNewProposal, both lifted out of their files and executed.
TAB_SAYS = {"test": "1", "active": "0", "all": None}          # what the Projects page's tab leaves for the project it starts
TAB_BORN = {"test": True, "active": False, "all": None}       # and what the project is born as
ELSEWHERE = "sheet-7"


def test_a_look_at_a_v2_page_starts_nothing_and_changes_nothing(ran):
    """F1 of the audit of round 2. "+ New project" on a Projects tab opens the live intake on a new project. The estimator LOOKS
    at a v2 page (the sidebar's link to its intake or its estimate page, which resumes the same project, and types nothing
    there) and goes Back to the live intake to type the bid. The v2 page's sandbox found no row and used to ARM the project as a
    test: it overwrote the one slot, "<id>:0" of the Active tab became "<id>:1", and the real bid was born a test and left the
    Active board. A look is not a write, so it leaves the start exactly as the tab left it and writes nothing to the server, and
    the bid typed afterwards is born as its tab said: a test from Test, a real bid from Active, and unsaid from All."""
    looks = ran["looks"]
    assert sorted(looks) == sorted("%s/%s" % (t, d) for t in TAB_SAYS for d in ("intake", "estimate")), sorted(looks)
    for name, r in sorted(looks.items()):
        tab = r["tab"]
        saw = r["looked"]
        assert saw["kind"] == r["door"] and saw["draft"] == r["id"], "%s: the look is not on the project: %r" % (name, saw)
        assert saw["report"]["crashed"] is None and "Nothing has been priced here yet" in saw["report"]["note"], (
            "%s: the v2 page did not open on a project nobody has saved: %r" % (name, saw["report"]))
        assert r["afterLook"]["rows"] == [], "%s: a look at a v2 page wrote a row: %r" % (name, r["afterLook"]["rows"])
        x = r["x"]
        assert x is not None and x["bornIsTest"] is TAB_BORN[tab] and x["is_test"] is TAB_BORN[tab] and x["flips"] == 0, (
            "%s: the bid was born %r, not as its tab said (%r): %r" % (name, (x or {}).get("bornIsTest"), TAB_BORN[tab], x))
        assert r["rowIds"] == [r["id"]], "%s: %r" % (name, r["rowIds"])
        assert r["startAtArrival"] == TAB_SAYS[tab], "%s: the tab left %r behind" % (name, r["startAtArrival"])
        assert r["afterLook"]["start"] == TAB_SAYS[tab], (
            "%s: the look changed what the project was started as, from %r to %r" % (name, TAB_SAYS[tab], r["afterLook"]["start"]))
        assert r["starts"] == {}, "%s: a start is still armed after the project was written: %r" % (name, r["starts"])


def test_the_active_tabs_real_bid_is_not_made_a_test_by_a_look_at_v2(ran):
    """F1 on its own, in the audit's words: a REAL bid started on the Projects page's Active tab. After a look at either v2
    page its start still reads "0", and the bid is born a real bid (is_test false), not a test."""
    for door in ("intake", "estimate"):
        r = ran["looks"]["active/" + door]
        assert r["x"]["bornIsTest"] is False and r["x"]["is_test"] is False, "%s: the real bid was born %r" % (door, r["x"])
        assert r["afterLook"]["start"] == "0", "%s: %r" % (door, r["afterLook"]["start"])


def test_a_project_typed_into_on_a_v2_page_is_a_test_project_whichever_tab_started_it(ran):
    """The look that is not a look, pinned so that it is a decision and not an accident. Whatever a v2 page WRITES is a test
    project (Hanz, 2026-08-11: everything the beta touches lands under Test), so a project started on the Active tab and then
    typed into on the v2 intake is born a test, filed by that page's own first write, and the estimate page edits it directly.
    Only a LOOK leaves it as its tab started it (the test above)."""
    r = ran["activeThenTypedInV2"]
    assert_filed_and_edited_directly(r, "started on the Active tab, typed into on the v2 intake")
    assert r["starts"] == {}, r["starts"]


def test_a_real_bid_that_wrote_something_is_copied_by_v2_and_never_edited_or_filed(ran):
    """A real bid started on the Active tab that has WRITTEN something on the live intake (a condition flipped), and is then opened on a
    v2 page. Its first save, sent as the live intake was left, has landed by then (the default timing): the v2 page finds a real
    project and does what it does with every real project, copies it. The real row is born a real bid and is only ever read by the
    v2 page; the copy is filed as a test."""
    r = ran["writtenThenLook"]["saved"]
    assert r["blobAfterWrite"].get("is_test") is False, r["blobAfterWrite"]
    assert r["x"] == {"is_test": False, "bornIsTest": False, "flips": 0, "beta_sandbox_of": None, "project_name": None}, r["x"]
    assert [q for q in reqs(r, "PUT", r["id"]) if not q["page"].startswith("v1intake")] == [], "the v2 page wrote to the real bid"
    assert r["beta"] is not None and r["beta"]["is_test"] is True and r["beta"]["beta_sandbox_of"] == r["id"], r["beta"]
    assert r["look"]["draftId"] == r["id"] + "-beta" and COPY in r["look"]["note"], r["look"]


NOT_SAVED_YET = {"notSavedYet": False, "notSavedYetEstimate": False, "allNotSavedYet": None, "allNotSavedYetEstimate": None}


def test_a_project_somebody_has_written_into_and_the_server_has_not_got_yet_stops_the_v2_page(ran):
    """The same, with the first save still on its way when the v2 page asks (a slow server, or one that refused it): the v2 page finds no
    row, and the project has been written into and says nothing of being a test (the Active tab's bid says it is not one, an All-tab
    project says nothing). It used to treat it as a project nobody has saved and save it as a test, which files a bid under Test (the
    All-tab one by SEEDING the row the other page's save then creates: it is born unsaid and ends up a test). It must not, and it must
    not let the estimator edit it either (its note would say "saved as a NEW test project" over a bid): it stops, says why, and writes
    nothing. The save that was on its way lands, and the project is what its tab said, with no test copy and nothing the v2 page wrote.
    The same slow server on a project started as a test is no problem: it is one, and the page edits it."""
    for name, word in sorted(NOT_SAVED_YET.items()):
        r = ran["writtenThenLook"][name]
        assert r["x"] == {"is_test": word, "bornIsTest": word, "flips": 0, "beta_sandbox_of": None, "project_name": None}, (name, r["x"])
        assert r["rowIds"] == [r["id"]], "%s: a test copy or another row appeared: %r" % (name, r["rowIds"])
        assert [q for q in reqs(r, "PUT", r["id"]) if not q["page"].startswith("v1intake")] == [], "%s: the v2 page wrote to the bid" % name
        look = r["look"]
        assert look["draftId"] == r["id"], (name, look)
        text = " ".join(look["loading"].split())
        assert "Estimating Tool v2 stopped" in text and "has not been saved yet" in text and "test copy" in text, (name, look["loading"])
        assert look["settled"] is not True, "%s: the page carried on" % name
    t = ran["writtenThenLook"]["testNotSavedYet"]
    assert t["x"] == {"is_test": True, "bornIsTest": True, "flips": 0, "beta_sandbox_of": None, "project_name": None}, t["x"]
    assert t["rowIds"] == [t["id"]] and t["look"]["loading"] == "" and DIRECT in t["look"]["note"], (t["rowIds"], t["look"])


def test_an_all_tab_project_that_wrote_something_is_copied_by_v2_never_edited_or_filed(ran):
    """The All tab says nothing of test-ness. A project started there that has written something and has its row (the default timing) is
    what every project with a row is to v2: copied, the copy filed as a test, the row only ever read, and it stays unsaid."""
    r = ran["writtenThenLook"]["allSaved"]
    assert r["x"] == {"is_test": None, "bornIsTest": None, "flips": 0, "beta_sandbox_of": None, "project_name": None}, r["x"]
    assert [q for q in reqs(r, "PUT", r["id"]) if not q["page"].startswith("v1intake")] == [], "the v2 page wrote to the bid"
    assert r["beta"] is not None and r["beta"]["is_test"] is True and r["beta"]["beta_sandbox_of"] == r["id"], r["beta"]


def test_a_gc_boards_active_start_is_not_filed_as_a_test_by_a_look_at_v2(ran):
    """F1's other door. A GC board's "+ New proposal" starts the bid with { audience: "GC" } already in the draft, so on the v2
    intake the sandbox sees a project WITH content and no row, which it saves at once, as a test. From the Active tab that is a
    real bid created as a test by looking at a page: nothing is saved by the look, the start still reads "0", and the bid typed
    afterwards in the live intake is born real. From the Test tab the start says test and the bid is born a test."""
    a = ran["gcBoardThenLook"]["active"]
    assert a["afterLook"]["rows"] == [], "the look created a row for a real bid: %r" % a["afterLook"]["rows"]
    assert "Nothing has been priced here yet" in a["afterLook"]["report"]["note"], a["afterLook"]["report"]["note"]
    assert a["x"]["bornIsTest"] is False and a["x"]["is_test"] is False and a["rowIds"] == [a["id"]], (a["x"], a["rowIds"])
    assert a["startAtArrival"] == "0" and a["afterLook"]["start"] == "0", (a["startAtArrival"], a["afterLook"]["start"])
    t = ran["gcBoardThenLook"]["test"]
    assert t["x"]["bornIsTest"] is True and t["x"]["is_test"] is True and t["rowIds"] == [t["id"]], (t["x"], t["rowIds"])
    assert t["startAtArrival"] == "1", t["startAtArrival"]


def _other_project_untouched(name, r):
    """What every abandoned-start run shares: the other project's page booted and it was only read."""
    assert r["lastKind"] == "v1intake" and r["lastDraft"] == ELSEWHERE, "%s: the other project's page did not boot" % name
    assert [q for q in reqs(r, id_=ELSEWHERE) if q["method"] != "GET"] == [], "%s: the other project was written to" % name
    assert r["other"]["is_test"] is None and r["other"]["bornIsTest"] is None, "%s: %r" % (name, r["other"])


def test_an_abandoned_board_start_with_nothing_typed_never_becomes_a_row(ran):
    """F2 of the audit of round 3 (and what became of round 3's own answer to F2 of round 2). A board's "+ New proposal" (the real
    startNewProposal of js/portal.js) opens the live intake; from the GC board it leaves { audience: "GC" } in the draft. Nothing is
    typed and the estimator opens ANOTHER project, so shared.js decides what to do with the abandoned blob under its own id. Round 3
    flushed it with the start in the PUT (a test from the Test tab, a real bid from the Active tab), which put a NAMELESS GC row on the
    board where staff work. A start is not work: the blob holds nothing the estimator typed (hasWork), so it is not flushed, and no row
    is ever made for it. The other project's page boots and it is only read."""
    ab = ran["abandonedBoardStart"]
    assert sorted(ab) == ["direct/active", "direct/test", "gc/active", "gc/test"], sorted(ab)
    for name, r in sorted(ab.items()):
        gc = name.startswith("gc/")
        assert r["blobAtArrival"] == ({"audience": "GC", "__draft_id": r["id"]} if gc else {}), "%s: %r" % (name, r["blobAtArrival"])
        assert r["x"] is None and r["rowIds"] == [ELSEWHERE], "%s: the abandoned start became a row: %r %r" % (name, r["x"], r["rowIds"])
        assert [q for q in reqs(r, id_=r["id"]) if q["method"] != "GET"] == [], "%s: something was sent for the abandoned project" % name
        assert r["startAfter"] == r["startAtArrival"], "%s: a start was spent although nothing was stored: %r" % (name, r["startAfter"])
        _other_project_untouched(name, r)


def test_an_abandoned_board_blob_that_holds_work_is_flushed_born_as_its_tab_said(ran):
    """The other side of the rule above, and what withStart is for. A blob that holds WORK which never went through setState (written by a
    page that did not say what the project was started as) is flushed as another project opens, and what the project was started as
    travels in that PUT: the row is born a test from the Test tab and a real bid from the Active tab. The start is used up once the
    server has stored it."""
    ab = ran["abandonedWithWork"]
    assert sorted(ab) == ["gc/active", "gc/test", "gc/test, its blob says real", "gc/test, its save refused"], sorted(ab)
    for name, want in (("gc/test", True), ("gc/active", False)):
        r = ab[name]
        assert r["blobAtArrival"] == {"audience": "GC", "__draft_id": r["id"], "project_name": "Typed Before Leaving"}, (
            "%s: %r" % (name, r["blobAtArrival"]))
        x = r["x"]
        assert x is not None and x["bornIsTest"] is want and x["is_test"] is want and x["flips"] == 0, (
            "%s: the abandoned blob was flushed without what it was started as: %r" % (name, x))
        assert r["startAtArrival"] == ("1" if want else "0"), "%s: %r" % (name, r["startAtArrival"])
        assert r["startAfter"] is None, "%s: the start was left armed after the row was stored: %r" % (name, r["startAfter"])
    for name, r in sorted(ab.items()):
        _other_project_untouched(name, r)


def test_a_copy_that_already_says_is_test_is_sent_as_it_is(ran):
    """The start is a default, never an order. The abandoned blob (a Test-tab start, "1") is flushed holding a word of its own (is_test
    false: a hydrate wrote what the server said, or a person did), and the PUT carries that word, not the start's."""
    r = ran["abandonedWithWork"]["gc/test, its blob says real"]
    assert r["blobAtArrival"].get("is_test") is False and r["startAtArrival"] == "1", (r["blobAtArrival"], r["startAtArrival"])
    assert r["x"] is not None and r["x"]["bornIsTest"] is False and r["x"]["is_test"] is False, (
        "the start overruled the blob's own word: %r" % r["x"])


def test_a_start_whose_flush_was_refused_stays_armed_for_the_next_save(ran):
    """The abandoned blob's own save is refused (HTTP 500): no row exists, so the start must NOT be spent. It is used up only once the
    server has stored a copy that carries it."""
    r = ran["abandonedWithWork"]["gc/test, its save refused"]
    assert r["x"] is None, "a row exists although the only save was refused: %r" % r["x"]
    assert r["startAtArrival"] == "1" and r["startAfter"] == "1", (r["startAtArrival"], r["startAfter"])


def test_the_v2_boards_new_estimate_starts_the_project_as_a_test_under_its_own_id(ran):
    """F2 of the audit of round 3, first half. The board's New estimate (the REAL startNew of js/v2-board.js, on the Direct and on the GC
    tab) clears the keys that make shared.js mint a new draft and then says what the project is started as, like every other door that
    starts one: a test. The start is minted with the project's id, so the page that opens finds it under the id it is on. (A
    { audience: "GC" } the GC tab leaves behind is not disturbed.)"""
    runs = ran["abandonedV2Start"]
    for name, blob in (("direct", {}), ("gc", {"audience": "GC"})):
        r = runs[name]
        assert r["startAtArrival"] == "1", "%s: the board started the project as %r, not as a test" % (name, r["startAtArrival"])
        assert r["blobAtStart"] == blob, "%s: the board left %r in the draft" % (name, r["blobAtStart"])


def test_an_abandoned_v2_start_never_becomes_a_nameless_row(ran):
    """F2 of the audit of round 3, second half. The GC tab's New estimate leaves { audience: "GC" } in the draft, which the page saves at once
    as a test. When that first save does not land (it is refused, or the estimator goes before the page has heard from the server) the blob is
    all that is left, and shared.js flushed it under its own id as the next project's page opened: a NAMELESS GC row born UNFILED, on the real
    board. Nothing the estimator typed is in it, so it is not flushed. The Direct tab leaves nothing at all. No save of the abandoned project is
    stored, and no row exists for it."""
    runs = ran["abandonedV2Start"]
    for name in ("direct", "gc, first save refused", "gc, left before the page heard from the server"):
        r = runs[name]
        assert r["x"] is None and r["rowIds"] == [ELSEWHERE], "%s: the abandoned start became a row: %r %r" % (name, r["x"], r["rowIds"])
        assert [q for q in reqs(r, "PUT", r["id"]) if q["status"] == 200] == [], "%s: a save of the abandoned project was stored" % name
        _other_project_untouched(name, r)
    # the control: when the page's own first save lands, the row is there, born a test, and nothing else has to be said
    g = runs["gc"]
    assert g["x"] is not None and g["x"]["bornIsTest"] is True and g["x"]["is_test"] is True and g["x"]["flips"] == 0, g["x"]
    _other_project_untouched("gc", g)


def test_a_v2_page_opened_by_a_bare_link_on_a_project_nobody_started_says_test_in_its_own_first_write(ran):
    """The flow in which the v2 page's OWN word ("this page created the project", TW.startsAsTest) is the only thing that can say a project is a
    test: the intake opened by a bare link (a bookmark, an address typed) on a project that nobody started, so nothing is stored under its id.
    Since the board's New estimate leaves a start, every flow that begins there is also covered by the start; this one is not, and it is
    what keeps the page's own word and setState's saying of it honest. Typed into and left, the project is born a test and edited directly."""
    for name in ("bareLink", "bareLinkAfterAutosave"):
        r = ran[name]
        assert r["startAtOpen"] is None, "%s: there was a start for the project, so this checks nothing about the page's own word: %r" % (name, r["startAtOpen"])
        assert_filed_and_edited_directly(r, name)


def test_leaving_with_two_saves_pending_sends_one_save_carrying_the_newest_edit(ran):
    """F4 of the audit of round 3. The v2 intake is left with TWO saves pending: the page's own 600 ms save has run (so shared.js's 2.5 s save of
    that copy is queued) and the estimator edits once more (so the page's own 600 ms timer is pending too). shared.js registers its pagehide
    handler first, so it sent the shared blob as it stood (the older copy), and then the page's handler saved and sent the newest: two keepalive
    PUTs of one draft. A server that finishes them out of order keeps the older copy (the first save sent is made slow here, and the row ended
    on the old address), and the browser counts keepalive bodies against ONE 64 KiB budget, so for a draft of half that size the second, the
    newest, is refused outright (a 36 KiB draft here: the row ended on the old address, nothing said). ONE save goes as the page goes, and it
    carries the newest edit."""
    runs = ran["twoSavesPending"]
    assert sorted(runs) == ["big", "small", "small, the first save slow"], sorted(runs)
    for name, r in sorted(runs.items()):
        gone = [q for q in reqs(r, "PUT", r["id"], page="intake") if q["at"] == r["pagehideAt"]]
        assert len(gone) == 1, "%s: %d saves were sent as the page went: %r" % (name, len(gone), [(q["sentAddress"], q["outcome"]) for q in gone])
        q = gone[0]
        assert q["keepalive"] is True and q["status"] == 200, "%s: the save was not sent as one that outlives the page, or was not stored: %r" % (name, q)
        assert q["sentAddress"] == NEWEST_ADDRESS, "%s: the save carried an older copy of the draft: %r" % (name, q["sentAddress"])
        assert r["xData"]["address"] == NEWEST_ADDRESS, "%s: the row holds %r, not the newest edit" % (name, r["xData"])
    big = [q for q in reqs(runs["big"], "PUT", runs["big"]["id"], page="intake") if q["at"] == runs["big"]["pagehideAt"]][0]
    assert big["bytes"] <= KEEPALIVE_ASKED and 2 * big["bytes"] > KEEPALIVE_LIMIT, (
        "the big draft is not one that fits a keepalive request and not two, so this checks nothing about the shared budget: %r" % big["bytes"])


DOOR_OPENING = "Opening Estimating Tool v2…"       # the beta door once it has asked the browser to leave
WANT_FLAG = {"test": True, "active": False, "all": None}     # what the Projects page's tab starts a project as


def test_the_beta_door_waits_for_the_project_to_be_saved_before_it_opens_the_v2_intake(ran):
    """F3 of the audit of round 3. The live intake's "Continue with Estimating Tool v2" saves the project and opens the v2 intake on it, which asks
    the server whether the project has a row: a project that is not a test is COPIED (the real bid left alone), one that is a test is edited
    directly, and one that has been written into and has no row yet looks like a project the server never heard of, so the page STOPS. The door
    left at once, and its save went out as the page went, so with a slow server (here: over a second) the v2 page asked before the row existed and
    stopped on a bid that was a moment from being saved. Now the door waits for the save to be answered, and the v2 page finds the project: from
    each Projects tab, on a fast server and a slow one, the real bid is born as its tab said and never written to by the v2 page, the Test tab's
    project is edited directly, and a project from Active or All is copied."""
    doors = ran["betaDoor"]
    assert sorted(doors) == sorted(t + "/" + s for t in WANT_FLAG for s in ("fast", "slow")), sorted(doors)
    for name, r in sorted(doors.items()):
        tab, slow, v2 = r["tab"], name.endswith("/slow"), r["v2"]
        assert v2 is not None and v2["kind"] == "intake", "%s: the door did not open the v2 intake: %r" % (name, v2)
        assert v2["loading"] == "", "%s: the v2 page STOPPED (%r) for a project that was a moment from being saved" % (name, v2["loading"])
        want = WANT_FLAG[tab]
        assert r["x"] == {"is_test": want, "bornIsTest": want, "flips": 0, "beta_sandbox_of": None, "project_name": "Real Polish Bid"}, (name, r["x"])
        if tab == "test":
            assert DIRECT in v2["note"] and COPY not in v2["note"] and r["beta"] is None and r["rowIds"] == [r["id"]], (name, v2["note"], r["rowIds"])
        else:
            assert COPY in v2["note"], "%s: the v2 page did not make a test copy of the bid: %r" % (name, v2["note"])
            assert r["beta"] is not None and r["beta"]["is_test"] is True and r["beta"]["beta_sandbox_of"] == r["id"], (name, r["beta"])
            assert r["rowIds"] == [r["id"], r["id"] + "-beta"], (name, r["rowIds"])
            assert [q for q in reqs(r, "PUT", r["id"]) if not q["page"].startswith("v1intake")] == [], "%s: the v2 page wrote to the real bid" % name
        # the door left only after the server had answered the save (and the slow runs really did take over a second to answer)
        first = r["livePuts"][0]
        assert first["repliedAt"] is not None and r["asked"][0]["at"] >= first["repliedAt"], (
            "%s: the door asked the browser to leave before its save was answered: %r %r" % (name, first, r["asked"]))
        if slow:
            assert first["repliedAt"] - first["at"] > 1000, "%s: the slow server was not slow, so this checks nothing: %r" % (name, first)


def test_the_beta_door_says_it_is_saving_ignores_a_second_press_and_is_given_back(ran):
    """The door's wait is shown (disabled, "Saving..."), as Continue's is on the v2 intake: a second press while it waits does nothing, one press is
    one save and one move, and when the browser does not go (the load was stopped, a prompt was answered no) the door gives itself back with its own
    markup (the BETA tag, not just its words) and works again."""
    fb = ran["betaDoorFeedback"]
    s = fb["saving"]
    early = s["samples"]["early"]
    assert early["disabled"] is True and early["saying"] == SAVING, "the door says nothing while it waits: %r" % early
    assert [p["accepted"] for p in s["presses"]] == [True, False], "a second press was taken: %r" % s["presses"]
    # and one that goes ROUND the disabled button (Enter in a box, a script) is ignored by the page itself
    assert s["forced"] == [400], s["forced"]
    assert len(s["asked"]) == 1 and len(reqs(s, "PUT", s["id"], page="v1intake")) == 1, (
        "one press must be one save and one move: %r %r" % (s["asked"], reqs(s, "PUT", s["id"], page="v1intake")))
    b = fb["blocked"]
    waiting = b["samples"]["waiting"]
    assert waiting["disabled"] is True and waiting["saying"] == DOOR_OPENING, "the door does not say it has asked to leave: %r" % waiting
    back = b["samples"]["afterGiveBack"]
    assert back["disabled"] is False and back["html"] == b["shipped"], "the door was not given back as it shipped: %r" % back
    assert [p["accepted"] for p in b["presses"]] == [True, True] and [a["blocked"] for a in b["asked"]] == [True, True], (
        "the door does not work again once it is given back: %r %r" % (b["presses"], b["asked"]))


def test_the_beta_door_leaves_when_its_wait_is_over_however_it_ends(ran):
    """A server that never answers does not trap the estimator on the live intake: the door waits at most its bound and then goes, as it always did
    (the v2 page then says there is no saved project to copy yet). A save that fails at once is not waited out."""
    ms = ran["betaDoorMs"]
    fb = ran["betaDoorFeedback"]
    hung = fb["hung"]
    assert hung["samples"]["midway"]["saying"] == SAVING and hung["samples"]["midway"]["disabled"] is True, hung["samples"]
    assert ms["wait"] is not None and 3000 <= ms["wait"] <= 15000 and ms["giveBack"] > ms["wait"], ms
    assert len(hung["asked"]) == 1 and abs(hung["asked"][0]["at"] - ms["wait"]) <= 60, (
        "the door did not leave when its wait was over (%r ms): %r" % (ms["wait"], hung["asked"]))
    failed = fb["failed"]
    assert len(failed["asked"]) == 1 and failed["asked"][0]["at"] < 1000, "a save that failed at once was waited out: %r" % failed["asked"]


def test_a_project_started_on_the_v2_board_is_a_test_whichever_page_writes_it_first(ran):
    """What a project is started as follows the PROJECT, not the page that happens to write it. The estimator starts a New estimate on the v2
    board and takes the same project to the LIVE intake (the sidebar's link resumes the browser's current draft), where a page that knows
    nothing of the board writes it: the row is born what the board started it as, a test, and not left unfiled on the board where staff work."""
    r = ran["v2BoardThenLiveIntake"]
    assert r["liveDraft"] == r["id"], "the live intake did not open on the board's project: %r" % (r["liveDraft"], )
    x = r["x"]
    assert x is not None and x["bornIsTest"] is True and x["is_test"] is True and x["flips"] == 0 and r["rowIds"] == [r["id"]], (
        "the project was born %r: %r" % ((x or {}).get("bornIsTest"), x))


def test_two_tabs_each_start_their_own_project_and_keep_their_own_start(ran):
    """F3 of the audit of round 2. Two tabs of one browser, each starting a project (one localStorage, a sessionStorage each):
    the v2 board's "+ New estimate" in both, and the Projects page's "+ New project" on the Test tab in one and on the Active
    tab in the other. Round 2 kept the start in ONE slot, so the second tab's start overwrote the first's before its first write
    and the first project was born unfiled (and forked on reopen). Now each project's start is its own, whichever tab types
    first. The tab that typed leaves exactly one row, born as ITS tab said; the other tab's project has no row; nothing forks."""
    t = ran["twoTabs"]
    assert sorted(t) == ["projectsA", "projectsB", "v2A", "v2B"], sorted(t)
    for name, r in sorted(t.items()):
        typed = r["ids"][r["first"]]
        want = False if (r["how"] == "projects" and r["first"] == "B") else True
        row = r["rows"].get(typed)
        assert row is not None and row["bornIsTest"] is want and row["is_test"] is want and row["flips"] == 0, (
            "%s: the project of the tab that typed (%s) was born %r, expected %r" % (name, typed, row, want))
        assert r["rowIds"] == [typed], "%s: a row was forked or another tab's project appeared: %r" % (name, r["rowIds"])
        assert [p for p in r["pages"] if p["crashed"]] == [] and not r["runaway"], name
    both = t["projectsA"]["startsAtOpen"]
    assert both == {t["projectsA"]["ids"]["A"]: "1", t["projectsA"]["ids"]["B"]: "0"}, (
        "the two tabs' starts did not both survive: %r" % both)


def test_every_door_out_of_the_intake_leaves_a_row_even_inside_the_debounce(ran):
    """F5 of the audit of round 2. The intake's own save waits 600 ms after an edit, and its pagehide handler flushed it with a
    plain request, which a page that is going cannot finish: leaving by a link, Back, a reload or a closed tab within 600 ms of an
    edit saved NOTHING (no row; the typed text only in localStorage), and the comment above it said keepalive. It is a keepalive
    request now, so every door at every time leaves a row, born filed, and the intake's own save at 100 ms goes out as the
    page goes and says so on the wire."""
    exits = ran["exits"]
    early = [e for e in exits if e["waitMs"] == 100]
    assert sorted(e["door"] for e in early) == ["back", "close", "link", "reload"], [e["door"] for e in early]
    for e in exits:
        flow = "%s at %d ms" % (e["door"], e["waitMs"])
        if e["door"] == "link":
            continue
        assert e["before"]["x"] is not None, "%s: the page left and saved nothing: %r" % (flow, e["before"])
    for e in early:
        flow = "%s at 100 ms" % e["door"]
        first = reqs(e, "PUT", e["id"], page="intake")[0]
        assert first["keepalive"] is True, "%s: the save sent as the page goes is not a keepalive request: %r" % (flow, first)


def test_a_v2_page_opened_on_a_project_nobody_had_written_does_not_make_it_a_test_once_somebody_has(ran):
    """TWO PAGES, ONE PROJECT (found by the same random walks). The sidebar's bare link resumes the browser's CURRENT draft, so a v2 page
    can open on the project another tab has just started, find no row and nothing written, and say "this page creates it as a test". The
    other tab's estimator then writes the project and its save creates the row, and the v2 page's estimator types. The v2 page's decision has
    gone stale, and its word is not the project's: the project stays what its own start said (a test from Test, a real bid from Active,
    unsaid from All) and is never SEEDED a test by the v2 page's write. (Both pages are on it, as they always were.)"""
    runs = ran["twoPagesOneProject"]
    assert sorted(runs) == ["active", "all", "test"], sorted(runs)
    want = {"all": None, "active": False, "test": True}
    for tab, r in sorted(runs.items()):
        assert r["v2Id"] == r["id"] and "Nothing has been priced here yet" in r["noteAtOpen"], (tab, r["v2Id"], r["noteAtOpen"])
        x = r["x"]
        assert x is not None and x["bornIsTest"] is want[tab] and x["is_test"] is want[tab] and x["flips"] == 0, (
            "%s: the project was born %r and ends %r, expected %r: %r" % (tab, (x or {}).get("bornIsTest"), (x or {}).get("is_test"), want[tab], x))
        assert r["rowIds"] == [r["id"]], (tab, r["rowIds"])


def test_another_tabs_new_project_cannot_empty_the_save_this_page_has_queued(ran):
    """THE ONE SHARED BLOB (found by random walks over the model while checking F3, and present in round 2 too). The browser keeps one copy
    of the draft in localStorage, and another tab's New project or New estimate WIPES it. This page's own 2.5 s save is still queued (its
    timer holds a copy of what the page wrote), and when the page goes inside that window shared.js re-read the shared blob, found it empty
    and PUT the empty object: a SAVED project's row was emptied (its name and address gone), and a NEW project's row was created empty and
    unfiled. The page now sends what it itself queued when the shared blob has been wiped, so the row is the project the estimator was
    working on, with its edit, and born as its start said: a saved test project keeps everything and gains the edit, a new test project
    is created filed with what was typed, and the live intake's Active bid is created real. The other tab's project, never typed into,
    has no row."""
    runs = ran["wiped"]
    assert sorted(runs) == ["new/projects", "new/v2", "new/v2, Continue pressed after the wipe", "new/v2, flushed after the wipe",
                            "new/v2, the other tab types", "saved/projects", "saved/v2", "saved/v2, the other tab types", "v1/projects",
                            "v1/v2"], sorted(runs)
    for name, r in sorted(runs.items()):
        if "types" in name:
            continue
        assert r["blobBeforeKeys"] > 5 and r["blobWipedKeys"] == 0, "%s: the run did not wipe the shared blob after the page wrote it" % name
        row, x = r["rowData"], r["x"]
        assert row is not None and x is not None, "%s: no row for the project" % name
        if r["kind"] == "saved":
            assert (row["project_name"], row["address"]) == ("Saved Test Job", "999 New Address"), "%s: the saved project was emptied or lost its edit: %r" % (name, row)
            assert x["is_test"] is True and x["flips"] == 0, (name, x)
        elif r["kind"] == "new":
            assert row["project_name"] == "Wiped New Job", "%s: the new project's row is empty or unfinished: %r" % (name, row)
            assert row["address"] == "100 Main St", (name, row)
            assert x["bornIsTest"] is True and x["is_test"] is True and x["flips"] == 0, "%s: the new project was not born filed: %r" % (name, x)
        else:
            assert row["project_name"] == "Wiped Walk-in", "%s: the Active tab's bid was created without what was typed: %r" % (name, row)
            assert x["bornIsTest"] is False and x["is_test"] is False and x["flips"] == 0, "%s: the Active tab's bid was not born real: %r" % (name, x)
        assert r["rowIds"] == [r["id"]], "%s: another row appeared: %r" % (name, r["rowIds"])


def test_the_queued_save_never_writes_another_projects_blob_under_this_projects_id(ran):
    """The other half of the rule above. When the other tab has gone on to TYPE, the shared blob is no longer empty: it is another
    project's, and this page's queued save must not write it under this project's id (it never did: the refusal is older than any of
    this). The page's own copy is lost with the blob, as it has always been when another tab has the keys, so this project has no row
    from this page (or, for a saved one, keeps what it had), and nothing of the other tab's is under its id."""
    new = ran["wiped"]["new/v2, the other tab types"]
    assert new["rowData"] is None or new["rowData"]["project_name"] != "Tab B Typed", new["rowData"]
    saved = ran["wiped"]["saved/v2, the other tab types"]
    assert saved["rowData"]["project_name"] == "Saved Test Job", "the saved project took another project's blob: %r" % saved["rowData"]
    for name in ("new/v2, the other tab types", "saved/v2, the other tab types"):
        r = ran["wiped"][name]
        assert (r["rowB"] or {}).get("project_name") == "Tab B Typed" and r["rowB"]["is_test"] is True, (
            "%s: the other tab's own project was not saved as itself: %r" % (name, r["rowB"]))
        assert r["rowData"] is None or r["rowData"]["project_name"] != "Tab B Typed", (name, r["rowData"])


def test_a_save_sent_as_the_page_goes_is_never_a_keepalive_request_the_browser_refuses(ran):
    """"Mind the 64 KiB cap". A saved project whose draft is over the browser's keepalive limit is edited on the v2 intake and
    left within 600 ms. The page must not ask for a keepalive request it knows will be refused ("TypeError: Failed to fetch",
    swallowed, nothing sent): it sends a plain one, which is no worse than before (the browser may finish it or drop it)."""
    r = ran["bigDraftLeftEarly"]
    puts = reqs(r, "PUT", "big-4", page="intake")
    assert puts, "the intake sent no save at all: %r" % r["requests"]
    for q in puts:
        assert q["keepalive"] is False and not q["outcome"].startswith("refused"), "the page asked for a keepalive the browser refuses: %r" % q


# ══ ROUND 4: the audit of round 3 (F1 to F6) ═════════════════════════════════════════════════════════════
# The harness runs are tests/js/new-estimate-test-flag-harness.js's round-4 scenarios, on the same model, which now also runs the board's
# REAL startNew, holds keepalive requests to one shared 64 KiB budget, and presses the live intake's beta door.
KEEPALIVE_LIMIT = 64 * 1024
KEEPALIVE_ASKED = 60 * 1024         # shared.js KEEPALIVE_MAX_BYTES: a little under the limit is the most a keepalive request is asked to carry
NEWEST_ADDRESS = "2 SECOND St (newest)"         # the last thing typed in the two-saves-pending run (the harness's own)


def test_a_draft_under_the_keepalive_limit_in_characters_and_over_it_in_bytes_goes_as_a_plain_request(ran):
    """F6 of the audit of round 3. keepaliveFits counts the body's size in UTF-8 BYTES, as the browser counts it against its 64 KiB
    keepalive limit, and nothing pinned that: a draft whose text is 2-, 3- or 4-byte characters (an accented name, a euro sign, an emoji
    in a note) is under the limit as `.length` says it and over it in bytes. A page that counted characters would ask for a keepalive
    request the browser refuses on the spot ("TypeError: Failed to fetch", swallowed, nothing sent), and the edit made in the last
    600 ms would go nowhere. Each family is checked on its own, and the premise is checked too (a body that is under the limit as
    characters and over it as bytes), so that a draft that is simply too big cannot make this pass for the wrong reason."""
    fams = ran["bytesNotCharacters"]
    assert sorted(fams) == ["2-byte", "3-byte", "4-byte"], sorted(fams)
    for name, r in sorted(fams.items()):
        puts = reqs(r, "PUT", "big-4", page="intake")
        assert puts, "%s: the intake sent no save at all: %r" % (name, r["requests"])
        for q in puts:
            assert q["chars"] < KEEPALIVE_ASKED and q["bytes"] > KEEPALIVE_LIMIT, (
                "%s: the draft is not under the limit as characters and over it as bytes, so this checks nothing: %r" % (name, q))
            assert q["keepalive"] is False and not q["outcome"].startswith("refused"), (
                "%s: the page asked for a keepalive request the browser refuses (it counted characters, not bytes): %r" % (name, q))


def test_a_v2_page_whose_shared_blob_belongs_to_another_project_stops_and_saves_nothing(ran):
    """F5 of the audit of round 3. The browser keeps ONE copy of the draft, and it can hold another tab's project while this tab's page
    is on its own id: tab A (the v2 board's New estimate, a name and an address typed), then tab B's New project from the Projects page,
    which wipes the shared blob, then tab A typing once more, which writes A's project into it, stamped for A. Tab B then opens a v2
    page by its bare link, which resumes B's own project, with the shared blob stamped for A. The sandbox found no row for B and saved
    that blob under B's id AS A TEST: B's project (started on the All tab) became a Test project holding tab A's name and address, with
    A's id inside it. It must STOP instead (the page stays on its loading line and says why), before it reads or saves anything: no row
    for B, nothing sent for B, A's project only A's, and the shared blob left as it was found."""
    runs = ran["foreignBlob"]
    assert sorted(runs) == ["estimate", "intake"], sorted(runs)
    for door, r in sorted(runs.items()):
        flow = "the v2 %s page" % door
        a, b = r["idA"], r["idB"]
        assert a != b and r["blobAfterBKeys"] == 0, "%s: the run did not start two projects and wipe the blob: %r" % (flow, (a, b, r["blobAfterBKeys"]))
        assert r["blobAfterA"] == {"stamp": a, "name": "Tab A Estimate"}, (
            "%s: the shared blob does not hold tab A's project while tab B is on its own, so this checks nothing: %r" % (flow, r["blobAfterA"]))
        assert r["v2"]["draftId"] == b, "%s: the page is not on tab B's project: %r" % (flow, r["v2"])
        text = " ".join(r["v2"]["loading"].split())
        assert "Estimating Tool v2 stopped" in text and "another tab" in text, "%s did not stop and say why: %r" % (flow, r["v2"])
        assert r["v2"]["settled"] is not True and r["v2"]["noteHidden"] is True, "%s carried on: %r" % (flow, r["v2"])
        assert r["rowBData"] is None and r["rowIds"] == [a], (
            "%s: tab B's project got a row (it holds %r) or another row appeared: %r" % (flow, r["rowBData"], r["rowIds"]))
        assert reqs(r, "PUT", b) == [], "%s: something was saved under tab B's id: %r" % (flow, reqs(r, "PUT", b))
        assert r["rowAData"] == {"project_name": "Tab A Estimate", "address": "1 A Street", "is_test": True}, (
            "%s: tab A's project is not its own any more: %r" % (flow, r["rowAData"]))
        assert r["blobEnd"]["stamp"] == a, "%s: the shared blob was changed: %r" % (flow, r["blobEnd"])


def test_a_save_made_for_one_project_never_carries_another_projects_blob(ran):
    """F5, the other half. The sandbox's own save writes the page's blob under an id it names. Asked to write a blob stamped for ANOTHER
    project under this project's id it must refuse (so that no path, now or later, can PUT it), and it still saves this project's own."""
    r = ran["savingAnotherProjectsBlob"]
    assert r["threw"], "the sandbox saved another project's blob under this project's id: %r" % r
    assert [p["name"] for p in r["puts"]] == ["This project's"] and r["ownStored"] is True, (
        "something other than this project's own save was sent: %r" % r["puts"])
    assert r["rowIds"] == ["mine-1"], r["rowIds"]


# ══ every check goes red when the code is changed ═════════════════════════════════════════════════════
# Each entry breaks one LINE of the sources in a scratch copy of the frontend, runs a harness on it, and the named check (a test
# above, called on the broken run's answers) has to fail. break_source refuses an anchor that is not there exactly once, so
# none of them can pass by applying nowhere; the harness runs outside the `raises`, so a break that merely crashes it is an
# error and never counts as the check noticing.
SHARED = "shared.js"
SANDBOX = "js/polish-sandbox.js"
INTAKE = "js/polish-intake.js"
PAGE = "polish-intake.html"
PROJECTS = "js/projects.js"
V2_BOARD = "js/v2-board.js"
INDEX = "js/index.js"

# shared.js: the stamp and its rules, where a project's start lives, and the copy that goes to the server
STAMP_CALL = "    if (id) sayWhatItWasStartedAs(id, merged, written);   // a NEW project's first write says what it was started as"
SET_STATE_WRITTEN = "    const written = hasWork(cur);   // before the merge: was anything already in the project's blob when this write came?"
STAMP_CONTENT = '    if (!Object.keys(blob).some((k) => k !== STAMP && k !== "is_test")) return;'
SPEND_KEY = "    try { localStorage.removeItem(startKey(id)); } catch {}"
SPEND_MARK = "    if (_startsAsTest === id) _startsAsTest = null;"
STAMP_KEEPS_A_WORD = '    if (!Object.prototype.hasOwnProperty.call(blob, "is_test")) blob.is_test = want;'
STAMP_NONE_PENDING = "    if (want === null) return;"
STAMP_WANT = "    const want = (_startsAsTest === id && !written) ? true : startOf(id);"
START_KEY = '  function startKey(id) { return NEW_IS_TEST_KEY + ":" + id; }'
START_MINTS_THE_ID = "      localStorage.setItem(DRAFT_ID_KEY, id);"
START_VALUE = '      localStorage.setItem(startKey(id), want ? "1" : "0");'
START_SAYS_NOTHING = "      if (want === null || want === undefined) return;"
START_LEGACY_SLOT = "      localStorage.removeItem(NEW_IS_TEST_KEY);"
STARTS_AS_TEST = "  function startsAsTest(id) { _startsAsTest = id || null; }"
PUT_WITH_START = "      const out = withStart(id, blob);"
PUT_SPENDS = '        if (ok && Object.prototype.hasOwnProperty.call(out, "is_test")) spendStart(id);'
QUEUED_FALLBACK = "    return (_queued && _queued.id === id) ? _queued.state : null;"
QUEUED_REMEMBERS = "    _queued = { id: id, state: state };"
QUEUED_EMPTY = "    if (Object.keys(blob).some((k) => k !== STAMP)) return blob;"
QUEUED_FOREIGN = "    if (blob[STAMP] && blob[STAMP] !== id) return null;"
PAGEHIDE_PUT = "    putDraft(id, blob, true);   // a save racing page teardown, as flushState({ keepalive: true }) is for a page that flushes its own"
SHARED_STANDS_DOWN = "    if (pageSends) return;"
FLUSH_PUT = "        putDraft(id, blob, !!(opts && opts.keepalive));"
WITH_START_CONTENT = "    if (!Object.keys(blob).some((k) => k !== STAMP)) return blob;"
WITH_START_WORD = '    if (!id || Object.prototype.hasOwnProperty.call(blob, "is_test")) return blob;'
KEEPALIVE_GATE = "        keepalive: keepalive && keepaliveFits(body),"
FLUSH_KEEPALIVE = "        putDraft(id, blob, !!(opts && opts.keepalive));"
SYNCED_LINE = "        if (ok && id === getDraftId() && getState()[STAMP] === id) markSynced(id, sent);"
KEEPALIVE_THREE_BYTES = "      else bytes += 3;"
KEEPALIVE_TWO_BYTES = "      else if (c < 0x800) bytes += 2;"
KEEPALIVE_FOUR_BYTES = "      else if (c >= 0xd800 && c <= 0xdbff) { bytes += 4; i++; }    // a surrogate pair is one four-byte character"
# the sandbox
SANDBOX_SAYS_TEST = "      body: JSON.stringify({ data: Object.assign({}, blob, { is_test: true }) }),"
SANDBOX_NOTE_UNSAVED = "          showUnsavedNote();"
SANDBOX_MARK = "      TW.startsAsTest(id);"
SANDBOX_REAL = "      var real = TW.startOf(id) === false;"
SANDBOX_STOPS_WRITTEN = "      if (said === false || (said !== true && written)) {"
SANDBOX_IF_SAVED = "        if (saved) {"
SANDBOX_SAVES = "        try { await saveThenFileAsTest(id, state); }"
SANDBOX_SAVE_FN = "  async function saveThenFileAsTest(id, blob) {"
SANDBOX_EXACT_TRISTATE = "    if (row.is_test === true || row.beta_sandbox_of) {"
SANDBOX_FOREIGN_STOP = "    if (state.__draft_id && state.__draft_id !== id) {"
SANDBOX_FOREIGN_SAVE = "    if (blob && blob.__draft_id && blob.__draft_id !== id) {"
# the intake
INTAKE_PAGEHIDE = "      try { save(); } finally { TW.flushState({ keepalive: true }); }"
INTAKE_DECLARES_LEAVE = "    TW.pageSavesOnLeave(function () { return !!saveTimer; });"
INTAKE_SAVE_TRY = "try { save(); }"
LEAVING_GUARD = "    if (leaving) return;"
SAY_SAVING = '      say("Saving…", true);'
SAY_OPENING = '      say("Opening the estimate…", true);'
GIVE_BACK_TIMER = "    setTimeout(giveBack, GIVE_BACK_MS);"
GIVE_BACK_ON_THROW = "      giveBack();"
GIVE_BACK_FN = "    var giveBack = function () { if (givenBack) return; givenBack = true; leaving = false; say(label, false); };"
LABEL_KEPT = '    var label = btn ? btn.textContent : "";'
SAY_FN = "    var say = function (text, off) { if (btn) { btn.disabled = off; btn.textContent = text; } };"
FLUSH_LINE = "        TW.flushState(),"
BOUND_LINE = "        new Promise(function (resolve) { timer = setTimeout(resolve, SAVE_WAIT_MS); })"
CLEAR_LINE = "    if (timer) clearTimeout(timer);"
CATCH_LINE = "    } catch (err) { /* flushState reports a failed save as false; it does not throw */ }"
BUTTON_TAG = '        <button type="submit" class="btn-primary" id="continue-btn">Continue to the estimate →</button>'
# the v2 board: what a New estimate starts the project as; and what shared.js does with a project nobody typed into
BOARD_STARTS_AS_TEST = "    TW.setNewProjectTestIntent(true);"
EVICTED_NEEDS_WORK = "    if (!hasWork(blob)) return;"
# the live intake's beta door (js/index.js)
DOOR_FLUSH = "        TW.flushState(),"
DOOR_BOUND = "        new Promise((resolve) => { timer = setTimeout(resolve, SAVE_WAIT_MS); }),"
DOOR_GUARD = "    if (betaLeaving) return;"
DOOR_SAYS_SAVING = '    betaBtn.textContent = "Saving…";'
DOOR_DISABLES = "    betaBtn.disabled = true;"
DOOR_SAYS_OPENING = '    betaBtn.textContent = "Opening Estimating Tool v2…";'
DOOR_GIVEN_BACK = "{ betaLeaving = false; betaBtn.disabled = false; betaBtn.innerHTML = markup; }"
DOOR_MARKUP_BACK = "betaBtn.innerHTML = markup;"
# the Projects page
ACTIVE_TAB = '        else if (CURRENT_FILTER === "active") TW.setNewProjectTestIntent(false);'
OTHER_TABS = "        else                                  TW.setNewProjectTestIntent(null);"


def broken(rel, old, new):
    return (rel, old, new)


# THE BOARD NOW LEAVES A START (round 4, F2), so a project that begins there is told "test" by TWO things: the page that writes it (setState, from the
# start or from the page's own word) and, for a copy that goes to the server, withStart. A flow that begins on the board therefore goes red only when
# BOTH are broken, and the page's own word only when the board's start is gone too. Each of them on its own is proved on a flow that has no start
# (the bare link), below.
# No write says what the project was started as, and no copy that goes to the server is given it either.
NOTHING_SAYS = (broken(SHARED, STAMP_CALL, "    void 0;"), broken(SHARED, PUT_WITH_START, "      const out = blob;"))
# The page does not arm its own word, and the board leaves no start for the project.
NEITHER_PAGE_NOR_BOARD = (broken(SANDBOX, SANDBOX_MARK, "      void 0;"), broken(V2_BOARD, BOARD_STARTS_AS_TEST, "    void 0;"))
# Everything is taken to be written already (the page's word is lost after a wipe), and the board leaves no start to say it instead.
WRITTEN_AND_NO_START = (broken(SHARED, SET_STATE_WRITTEN, "    const written = true;"), broken(V2_BOARD, BOARD_STARTS_AS_TEST, "    void 0;"))


def every(test, modes):
    """A parametrized test as one check over all its parameters, under the test's own name."""
    def check(ran):
        for mode in modes:
            test(ran, mode)
    check.__name__ = test.__name__
    return check


# the intake page's own test of what it tells shared.js as it goes (tests/test_polish_intake_page.py), called on the answers of a broken copy
import test_polish_intake_page as _intake_page_tests


def check_the_intake_hands_the_pagehide_save_over(intake):
    _intake_page_tests.test_the_intake_tells_shared_js_when_its_own_pagehide_save_will_send_and_sends_even_if_its_save_throws(intake)


FILING_MODES = ("http500", "okfalse", "network", "hang", "html", "gone")
SAVE_MODES = ("http500", "okfalse", "network")
check_nothing_depends_on_a_filing_request = every(test_nothing_depends_on_a_filing_request, FILING_MODES)
check_a_save_that_fails_once = every(test_a_save_that_fails_once_still_ends_born_filed, SAVE_MODES)
check_a_save_that_cannot_be_made = every(test_a_save_that_cannot_be_made_is_said_and_never_claimed_as_a_filing, SAVE_MODES)

# name -> (harness, (the lines to break: (file, anchor line, what it becomes), ...), the check)
BREAKS = {
    # ── the seed: setState says what the project was started as ──
    "no write says what the project was started as (every flow)": (
        "world", NOTHING_SAYS, test_a_new_project_is_born_filed_whichever_way_it_leaves),
    "no write says what the project was started as (the first save, on the wire)": (
        "world", NOTHING_SAYS, test_the_first_save_says_what_the_project_was_started_as),
    "no write says what the project was started as (every other door)": (
        "world", NOTHING_SAYS, test_every_other_door_out_of_the_intake_leaves_one_row_born_filed),
    "no write says what the project was started as (the next new estimate)": (
        "world", NOTHING_SAYS, test_the_next_new_estimate_does_not_leave_the_first_one_behind),
    "no write says what the project was started as (the latencies)": (
        "world", NOTHING_SAYS, test_whatever_the_latencies_the_new_project_is_born_filed_and_never_forked),
    "no write says what the project was started as (a /test that goes wrong)": (
        "world", NOTHING_SAYS, check_nothing_depends_on_a_filing_request),
    "no write says what the project was started as (a save that fails once)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), check_a_save_that_fails_once),
    "no write says what the project was started as (a stale tab)": (
        "world", NOTHING_SAYS, test_a_stale_tab_cannot_undo_a_humans_filing),
    "no write says what the project was started as (a save that cannot be made at all)": (
        "world", NOTHING_SAYS, test_a_new_project_that_could_not_be_saved_as_the_page_opened_is_still_created_filed),
    "a server that never answers: the first save says nothing": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_a_server_that_never_answers_does_not_trap_the_estimator),
    "a save that fails at once: the first save says nothing": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_a_save_that_fails_at_once_is_not_waited_out),
    "the sandbox never says the project is a test (every flow)": (
        "world", NEITHER_PAGE_NOR_BOARD, test_a_new_project_is_born_filed_whichever_way_it_leaves),
    "the sandbox never says the project is a test (every other door)": (
        "world", NEITHER_PAGE_NOR_BOARD, test_every_other_door_out_of_the_intake_leaves_one_row_born_filed),
    "the sandbox never says the project is a test (a save that cannot be made at all)": (
        "world", NEITHER_PAGE_NOR_BOARD,
        test_a_new_project_that_could_not_be_saved_as_the_page_opened_is_still_created_filed),
    "the sandbox never says the project is a test (two tabs)": (
        "world", NEITHER_PAGE_NOR_BOARD, test_two_tabs_each_start_their_own_project_and_keep_their_own_start),
    # ── the stamp's own rules ──
    "an empty write says it and uses the start up": (
        "world", (broken(SHARED, STAMP_CONTENT, "    void 0;"),),
        test_the_start_is_said_by_the_first_write_that_has_content_and_only_for_its_own_project),
    "the start is never spent, even by a stored save": (
        "world", (broken(SHARED, SPEND_KEY, "    void 0;"),),
        test_a_start_is_spent_when_the_server_has_stored_a_copy_that_carries_it_and_not_before),
    "the start is never spent, even by a stored save (an abandoned board start)": (
        "world", (broken(SHARED, SPEND_KEY, "    void 0;"),), test_an_abandoned_board_blob_that_holds_work_is_flushed_born_as_its_tab_said),
    "this page's own word is never spent": (
        "world", (broken(SHARED, SPEND_MARK, "    void 0;"),),
        test_a_start_is_spent_when_the_server_has_stored_a_copy_that_carries_it_and_not_before),
    "the write that says the start spends it": (
        "world", (broken(SHARED, STAMP_KEEPS_A_WORD,
                         '    spendStart(id); if (!Object.prototype.hasOwnProperty.call(blob, "is_test")) blob.is_test = want;'),),
        test_a_start_is_spent_when_the_server_has_stored_a_copy_that_carries_it_and_not_before),
    "the write that says the start spends it (a blob wiped before the save went)": (
        "world", (broken(SHARED, STAMP_KEEPS_A_WORD,
                         '    spendStart(id); if (!Object.prototype.hasOwnProperty.call(blob, "is_test")) blob.is_test = want;'),),
        test_another_tabs_new_project_cannot_empty_the_save_this_page_has_queued),
    "a start overrules a blob that already says is_test": (
        "world", (broken(SHARED, STAMP_KEEPS_A_WORD, "    blob.is_test = want;"),),
        test_the_start_is_said_by_the_first_write_that_has_content_and_only_for_its_own_project),
    "a write says something even when no start is pending": (
        "world", (broken(SHARED, STAMP_NONE_PENDING, "    if (want === undefined) return;"),),
        test_the_start_is_said_by_the_first_write_that_has_content_and_only_for_its_own_project),
    "a write for a project with no start says is_test null": (
        "world", (broken(SHARED, STAMP_NONE_PENDING, "    if (want === undefined) return;"),),
        test_the_start_is_said_by_the_first_write_that_has_content_and_only_for_its_own_project),
    # ── a project's start is its own: one key per project, minted with the project ──
    "every project's start is under one key (another project's start is applied to this one)": (
        "world", (broken(SHARED, START_KEY, "  function startKey(id) { return NEW_IS_TEST_KEY; }"),),
        test_the_start_is_said_by_the_first_write_that_has_content_and_only_for_its_own_project),
    "every project's start is under one key (a real bid opened after an abandoned New project)": (
        "world", (broken(SHARED, START_KEY, "  function startKey(id) { return NEW_IS_TEST_KEY; }"),),
        test_a_real_bid_saved_in_the_live_intake_is_never_flagged),
    "every project's start is under one key (two tabs)": (
        "world", (broken(SHARED, START_KEY, "  function startKey(id) { return NEW_IS_TEST_KEY; }"),),
        test_two_tabs_each_start_their_own_project_and_keep_their_own_start),
    "New project does not leave the project's id behind (the live intake)": (
        "world", (broken(SHARED, START_MINTS_THE_ID, "      void 0;"),),
        test_a_project_started_from_the_test_tab_is_born_filed_through_the_live_intake),
    "New project does not leave the project's id behind (what the Projects page hands over)": (
        "world", (broken(SHARED, START_MINTS_THE_ID, "      void 0;"),),
        test_the_projects_page_hands_the_live_intake_the_tab_it_started_from),
    "New project stores the Active tab's start as a test": (
        "world", (broken(SHARED, START_VALUE, '      localStorage.setItem(startKey(id), "1");'),),
        test_a_project_started_from_the_active_tab_is_born_as_a_real_bid),
    "New project from All or Inactive mints a start too": (
        "world", (broken(SHARED, START_SAYS_NOTHING, "      if (false) return;"),), test_new_project_mints_the_projects_id_with_its_own_start),
    "New project leaves the earlier version's slot where it was": (
        "world", (broken(SHARED, START_LEGACY_SLOT, "      void 0;"),), test_new_project_mints_the_projects_id_with_its_own_start),
    # ── a look starts nothing; a v2 page's own first write says test ──
    "a write ignores this page's own word": (
        "world", (broken(SHARED, STAMP_WANT, "    const want = startOf(id);"),),
        test_a_v2_pages_own_word_is_said_by_the_first_write_it_makes_and_only_by_that),
    "this page's own word is said over a project somebody else has since written": (
        "world", (broken(SHARED, STAMP_WANT, "    const want = _startsAsTest === id ? true : startOf(id);"),),
        test_a_v2_page_opened_on_a_project_nobody_had_written_does_not_make_it_a_test_once_somebody_has),
    "nothing is ever taken to be written already": (
        "world", (broken(SHARED, SET_STATE_WRITTEN, "    const written = false;"),),
        test_a_v2_page_opened_on_a_project_nobody_had_written_does_not_make_it_a_test_once_somebody_has),
    "everything is taken to be written already (a blob that was wiped to nothing)": (
        "world", (broken(SHARED, SET_STATE_WRITTEN, "    const written = true;"),),
        test_a_start_is_spent_when_the_server_has_stored_a_copy_that_carries_it_and_not_before),
    "everything is taken to be written already (Continue after the wipe)": (
        "world", WRITTEN_AND_NO_START,
        test_another_tabs_new_project_cannot_empty_the_save_this_page_has_queued),
    "a start the Projects page left beats this page's own word": (
        "world", (broken(SHARED, STAMP_WANT,
                         "    const want = startOf(id) !== null ? startOf(id) : (_startsAsTest === id ? true : null);"),),
        test_a_project_typed_into_on_a_v2_page_is_a_test_project_whichever_tab_started_it),
    "a start the Projects page left beats this page's own word (the stamp's own rules)": (
        "world", (broken(SHARED, STAMP_WANT,
                         "    const want = startOf(id) !== null ? startOf(id) : (_startsAsTest === id ? true : null);"),),
        test_a_v2_pages_own_word_is_said_by_the_first_write_it_makes_and_only_by_that),
    "a look arms the project as a test (every look)": (
        "world", (broken(SHARED, STARTS_AS_TEST,
                         '  function startsAsTest(id) { _startsAsTest = id || null; try { localStorage.setItem(startKey(id), "1"); } catch {} }'),),
        test_a_look_at_a_v2_page_starts_nothing_and_changes_nothing),
    "a look arms the project as a test (the Active tab's real bid)": (
        "world", (broken(SHARED, STARTS_AS_TEST,
                         '  function startsAsTest(id) { _startsAsTest = id || null; try { localStorage.setItem(startKey(id), "1"); } catch {} }'),),
        test_the_active_tabs_real_bid_is_not_made_a_test_by_a_look_at_v2),
    "a look at a v2 page creates a test row for a real bid that has content": (
        "world", (broken(SANDBOX, SANDBOX_REAL, "      var real = false;"),),
        test_a_gc_boards_active_start_is_not_filed_as_a_test_by_a_look_at_v2),
    "a project the server has not got yet is saved as a test by a look": (
        "world", (broken(SANDBOX, SANDBOX_STOPS_WRITTEN, "      if (false) {"),),
        test_a_project_somebody_has_written_into_and_the_server_has_not_got_yet_stops_the_v2_page),
    # ── a copy that never went through setState carries the start, and spends it only when it is stored ──
    "a copy that never went through setState goes without the start": (
        "world", (broken(SHARED, PUT_WITH_START, "      const out = blob;"),), test_an_abandoned_board_blob_that_holds_work_is_flushed_born_as_its_tab_said),
    "the start is not spent once the server has stored it": (
        "world", (broken(SHARED, PUT_SPENDS, "        void 0;"),), test_an_abandoned_board_blob_that_holds_work_is_flushed_born_as_its_tab_said),
    "the start is spent by a save the server refused": (
        "world", (broken(SHARED, PUT_SPENDS, '        if (Object.prototype.hasOwnProperty.call(out, "is_test")) spendStart(id);'),),
        test_a_start_whose_flush_was_refused_stays_armed_for_the_next_save),
    "the start is spent by a save the server refused (the stamp's own rules)": (
        "world", (broken(SHARED, PUT_SPENDS, '        if (Object.prototype.hasOwnProperty.call(out, "is_test")) spendStart(id);'),),
        test_a_start_is_spent_when_the_server_has_stored_a_copy_that_carries_it_and_not_before),
    # ── the shared blob is wiped by another tab's New project: the page sends what it itself queued ──
    "the page's queued copy is not sent when the shared blob was wiped": (
        "world", (broken(SHARED, QUEUED_FALLBACK, "    return null;"),),
        test_another_tabs_new_project_cannot_empty_the_save_this_page_has_queued),
    "the page forgets what it queued": (
        "world", (broken(SHARED, QUEUED_REMEMBERS, "    void 0;"),),
        test_another_tabs_new_project_cannot_empty_the_save_this_page_has_queued),
    "an empty shared blob is sent over the project": (
        "world", (broken(SHARED, QUEUED_EMPTY, "    return blob;"),),
        test_another_tabs_new_project_cannot_empty_the_save_this_page_has_queued),
    "another project's blob is written under this project's id": (
        "world", (broken(SHARED, QUEUED_FOREIGN, "    void 0;"),),
        test_the_queued_save_never_writes_another_projects_blob_under_this_projects_id),
    "the page going re-reads the shared blob instead of its queued copy": (
        "world", (broken(SHARED, PAGEHIDE_PUT, "    putDraft(id, getState(), true);"),),
        test_another_tabs_new_project_cannot_empty_the_save_this_page_has_queued),
    "a flush re-reads the shared blob instead of the queued copy": (
        "world", (broken(SHARED, FLUSH_PUT, "        putDraft(id, getState(), !!(opts && opts.keepalive));"),),
        test_another_tabs_new_project_cannot_empty_the_save_this_page_has_queued),
    "the start is put on a copy with nothing in it": (
        "world", (broken(SHARED, WITH_START_CONTENT, "    void 0;"),), test_a_blob_with_nothing_in_it_is_sent_as_it_is),
    "the start overrules a word the copy already holds": (
        "world", (broken(SHARED, WITH_START_WORD, "    if (!id) return blob;"),), test_a_copy_that_already_says_is_test_is_sent_as_it_is),
    # ── leaving inside the debounce ──
    "the intake's pagehide save is not a keepalive request": (
        "world", (broken(INTAKE, INTAKE_PAGEHIDE, "      try { save(); } finally { TW.flushState(); }"),),
        test_every_door_out_of_the_intake_leaves_a_row_even_inside_the_debounce),
    "flushState drops the keepalive it was asked for": (
        "world", (broken(SHARED, FLUSH_KEEPALIVE, "        putDraft(id, blob);"),),
        test_every_door_out_of_the_intake_leaves_a_row_even_inside_the_debounce),
    "a draft too big for a keepalive request is asked to go as one": (
        "world", (broken(SHARED, KEEPALIVE_GATE, "        keepalive: keepalive,"),),
        test_a_save_sent_as_the_page_goes_is_never_a_keepalive_request_the_browser_refuses),
    # ── the sandbox: a save that creates a project as a test, and says so honestly ──
    "the sandbox's save does not say is_test (the page that creates the project)": (
        "world", (broken(SANDBOX, SANDBOX_SAYS_TEST, "      body: JSON.stringify({ data: blob }),"),),
        test_a_new_project_is_born_filed_whichever_way_it_leaves),
    "the sandbox's save does not say is_test (the copy)": (
        "world", (broken(SANDBOX, SANDBOX_SAYS_TEST, "      body: JSON.stringify({ data: blob }),"),),
        test_a_real_project_is_copied_never_filed_and_never_written_to),
    "the sandbox never saves the project it says it saved": (
        "world", (broken(SANDBOX, SANDBOX_SAVES, "        try { void 0; }"),),
        test_a_gc_tab_bid_is_saved_and_filed_as_the_intake_opens),
    "a save that failed is said to be filed": (
        "world", (broken(SANDBOX, SANDBOX_IF_SAVED, "        if (true) {"),), check_a_save_that_cannot_be_made),
    "a save that failed is not said at all": (
        "world", (broken(SANDBOX, SANDBOX_NOTE_UNSAVED, "          showDirectNote(false);"),), check_a_save_that_cannot_be_made),
    "a page's save waits for a filing that never answers": (
        "world", (broken(SANDBOX, SANDBOX_SAVE_FN, SANDBOX_SAVE_FN + " await fileAsTest(id);"),),
        test_the_next_page_boots_while_a_filing_never_answers),
    "a project nobody has filed is edited in place": (
        "world", (broken(SANDBOX, SANDBOX_EXACT_TRISTATE, "    if (row.is_test !== false || row.beta_sandbox_of) {"),),
        test_a_real_project_is_copied_never_filed_and_never_written_to),
    "a project nobody has filed is edited in place (a stale start)": (
        "world", (broken(SANDBOX, SANDBOX_EXACT_TRISTATE, "    if (row.is_test !== false || row.beta_sandbox_of) {"),),
        test_a_stale_start_for_a_project_that_has_moved_on_is_copied_and_never_filed),
    "a real bid is edited in place (through the intake)": (
        "world", (broken(SANDBOX, SANDBOX_EXACT_TRISTATE, "    if (row.is_test !== false || row.beta_sandbox_of) {"),),
        test_a_real_project_is_copied_and_never_written_to_or_filed),
    # ── the live intake, through the Projects page ──
    "the Active tab says nothing": (
        "world", (broken(PROJECTS, ACTIVE_TAB, '        else if (CURRENT_FILTER === "active") TW.setNewProjectTestIntent(null);'),),
        test_a_project_started_from_the_active_tab_is_born_as_a_real_bid),
    "All and Inactive start a real bid": (
        "world", (broken(PROJECTS, OTHER_TABS, "        else                                  TW.setNewProjectTestIntent(false);"),),
        test_all_and_inactive_start_a_project_that_nobody_has_said_anything_about),
    # ── the record of what the server holds ──
    "the first save is never recorded as stored": (
        "world", (broken(SHARED, SYNCED_LINE, "        void 0;"),),
        test_the_record_of_what_the_server_holds_is_written_as_the_first_save_is_stored),
    # ── Continue: the wait ──
    "Continue leaves without waiting for the save": (
        "world", (broken(INTAKE, FLUSH_LINE, "        Promise.resolve(true),"),), test_a_server_that_never_answers_does_not_trap_the_estimator),
    "Continue waits for a save that never answers, for ever": (
        "world", (broken(INTAKE, BOUND_LINE, "        new Promise(function () {})"),), test_a_server_that_never_answers_does_not_trap_the_estimator),
    "Continue leaves without waiting for a draft too big for a keepalive request": (
        "world", (broken(INTAKE, FLUSH_LINE, "        Promise.resolve(true),"),),
        test_continue_saves_a_draft_too_big_for_a_keepalive_request_before_it_leaves),
    "Continue waits for a save that failed at once, for the whole bound": (
        "world", (broken(INTAKE, FLUSH_LINE, "        new Promise(function () {}),"),), test_a_save_that_fails_at_once_is_not_waited_out),
    "Continue does not wait for the save (the page alone)": (
        "intake", (broken(INTAKE, FLUSH_LINE, "        Promise.resolve(true),"),),
        test_continue_says_it_is_saving_and_ignores_a_second_press_on_the_page_alone),
    "Continue's wait has no bound (the page alone)": (
        "intake", (broken(INTAKE, BOUND_LINE, "        new Promise(function () {})"),), test_continue_leaves_when_the_wait_is_over_however_it_ends),
    "Continue leaves its wait's timer armed": (
        "intake", (broken(INTAKE, CLEAR_LINE, "    void 0;"),), test_continue_gives_the_button_back_on_the_page_alone),
    "a save that throws stops Continue": (
        "intake", (broken(INTAKE, CATCH_LINE, "    } catch (err) { return; }"),), test_continue_leaves_when_the_wait_is_over_however_it_ends),
    # ── Continue: the button ──
    "Continue says nothing while it saves": (
        "world", (broken(INTAKE, SAY_SAVING, "      void 0;"),), test_continue_tells_the_estimator_it_is_saving),
    "Continue's button is never disabled": (
        "world", (broken(INTAKE, SAY_FN, "    var say = function (text, off) { if (btn) { btn.textContent = text; } };"),),
        test_continue_tells_the_estimator_it_is_saving),
    "the page has no Continue button to speak through": (
        "world", (broken(PAGE, BUTTON_TAG, BUTTON_TAG.replace(' id="continue-btn"', "")),), test_continue_tells_the_estimator_it_is_saving),
    "the button is not given back when the browser does not go": (
        "world", (broken(INTAKE, GIVE_BACK_TIMER, "    void 0;"),), test_continue_gives_the_button_back_when_the_browser_does_not_go),
    "Continue is dead after the button is given back": (
        "world", (broken(INTAKE, GIVE_BACK_FN, GIVE_BACK_FN.replace(" leaving = false;", "")),),
        test_continue_gives_the_button_back_when_the_browser_does_not_go),
    "the button is given back without its label": (
        "world", (broken(INTAKE, LABEL_KEPT, '    var label = "";'),), test_continue_gives_the_button_back_when_the_browser_does_not_go),
    "a second press is accepted (the page alone)": (
        "intake", (broken(INTAKE, LEAVING_GUARD, "    void 0;"),),
        test_continue_says_it_is_saving_and_ignores_a_second_press_on_the_page_alone),
    "Continue says nothing while it saves (the page alone)": (
        "intake", (broken(INTAKE, SAY_SAVING, "      void 0;"),),
        test_continue_says_it_is_saving_and_ignores_a_second_press_on_the_page_alone),
    "Continue does not say it is opening the estimate (the page alone)": (
        "intake", (broken(INTAKE, SAY_OPENING, "      void 0;"),), test_continue_gives_the_button_back_on_the_page_alone),
    "the button is not given back when the browser does not go (the page alone)": (
        "intake", (broken(INTAKE, GIVE_BACK_TIMER, "    void 0;"),), test_continue_gives_the_button_back_on_the_page_alone),
    "the button is left saying Saving when the page throws (the page alone)": (
        "intake", (broken(INTAKE, GIVE_BACK_ON_THROW, "      void 0;"),), test_continue_gives_the_button_back_on_the_page_alone),
    "Continue is dead after the button is given back (the page alone)": (
        "intake", (broken(INTAKE, GIVE_BACK_FN, GIVE_BACK_FN.replace(" leaving = false;", "")),),
        test_continue_gives_the_button_back_on_the_page_alone),
    "the page alone has no Continue button to speak through": (
        "intake", (broken(PAGE, BUTTON_TAG, BUTTON_TAG.replace(' id="continue-btn"', "")),),
        test_continue_says_it_is_saving_and_ignores_a_second_press_on_the_page_alone),
    # ── round 4, F4: one save as the page goes ──
    "shared.js sends its own save as the page goes although the page's will send": (
        "world", (broken(SHARED, SHARED_STANDS_DOWN, "    void 0;"),),
        test_leaving_with_two_saves_pending_sends_one_save_carrying_the_newest_edit),
    "the intake does not tell shared.js its own pagehide save will send (the real pages)": (
        "world", (broken(INTAKE, INTAKE_DECLARES_LEAVE, "    void 0;"),),
        test_leaving_with_two_saves_pending_sends_one_save_carrying_the_newest_edit),
    "the intake tells shared.js its own pagehide save will send when nothing is pending (the real pages)": (
        "world", (broken(INTAKE, INTAKE_DECLARES_LEAVE, "    TW.pageSavesOnLeave(function () { return true; });"),),
        test_every_door_out_of_the_intake_leaves_a_row_even_inside_the_debounce),
    "the intake does not tell shared.js its own pagehide save will send (the page alone)": (
        "intake", (broken(INTAKE, INTAKE_DECLARES_LEAVE, "    void 0;"),), check_the_intake_hands_the_pagehide_save_over),
    "the intake tells shared.js its own pagehide save will send when nothing is pending (the page alone)": (
        "intake", (broken(INTAKE, INTAKE_DECLARES_LEAVE, "    TW.pageSavesOnLeave(function () { return true; });"),),
        check_the_intake_hands_the_pagehide_save_over),
    "the intake's pagehide save that throws skips the flush (the page alone)": (
        "intake", (broken(INTAKE, INTAKE_SAVE_TRY, "save(); try { }"),), check_the_intake_hands_the_pagehide_save_over),
    # ── round 4, F3: the beta door waits for the save, says so, and gives itself back ──
    "the beta door leaves without waiting for its save": (
        "world", (broken(INDEX, DOOR_FLUSH, "        Promise.resolve(true),"),),
        test_the_beta_door_waits_for_the_project_to_be_saved_before_it_opens_the_v2_intake),
    "the beta door waits for a save that never answers, for ever": (
        "world", (broken(INDEX, DOOR_BOUND, "        new Promise(() => {}),"),),
        test_the_beta_door_leaves_when_its_wait_is_over_however_it_ends),
    "the beta door waits for a save that failed at once, for the whole bound": (
        "world", (broken(INDEX, DOOR_FLUSH, "        new Promise(() => {}),"),),
        test_the_beta_door_leaves_when_its_wait_is_over_however_it_ends),
    "the beta door says nothing while it saves": (
        "world", (broken(INDEX, DOOR_SAYS_SAVING, "    void 0;"),),
        test_the_beta_door_says_it_is_saving_ignores_a_second_press_and_is_given_back),
    "the beta door is never disabled": (
        "world", (broken(INDEX, DOOR_DISABLES, "    void 0;"),),
        test_the_beta_door_says_it_is_saving_ignores_a_second_press_and_is_given_back),
    "the beta door takes a second press": (
        "world", (broken(INDEX, DOOR_GUARD, "    void 0;"),),
        test_the_beta_door_says_it_is_saving_ignores_a_second_press_and_is_given_back),
    "the beta door does not say it has asked to leave": (
        "world", (broken(INDEX, DOOR_SAYS_OPENING, "    void 0;"),),
        test_the_beta_door_says_it_is_saving_ignores_a_second_press_and_is_given_back),
    "the beta door is not given back when the browser does not go": (
        "world", (broken(INDEX, DOOR_GIVEN_BACK, "{ void 0; }"),),
        test_the_beta_door_says_it_is_saving_ignores_a_second_press_and_is_given_back),
    "the beta door is given back without its markup": (
        "world", (broken(INDEX, DOOR_MARKUP_BACK, "void 0;"),),
        test_the_beta_door_says_it_is_saving_ignores_a_second_press_and_is_given_back),
    # ── round 4, F2: the board leaves a start, so each mechanism on its own is proved on a flow that has none ──
    "no write says what the project was started as (a project with no start)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),),
        test_a_v2_page_opened_by_a_bare_link_on_a_project_nobody_started_says_test_in_its_own_first_write),
    "the sandbox never says the project is a test (a project with no start)": (
        "world", (broken(SANDBOX, SANDBOX_MARK, "      void 0;"),),
        test_a_v2_page_opened_by_a_bare_link_on_a_project_nobody_started_says_test_in_its_own_first_write),
    # ── round 4, F2: the v2 board says what a project is started as; an abandoned start is not work ──
    "the v2 board starts a project without saying what it is started as (the start)": (
        "world", (broken(V2_BOARD, BOARD_STARTS_AS_TEST, "    void 0;"),),
        test_the_v2_boards_new_estimate_starts_the_project_as_a_test_under_its_own_id),
    "the v2 board starts a project without saying what it is started as (a live intake writes it)": (
        "world", (broken(V2_BOARD, BOARD_STARTS_AS_TEST, "    void 0;"),),
        test_a_project_started_on_the_v2_board_is_a_test_whichever_page_writes_it_first),
    "a blob nobody typed into is flushed when another project opens (the Projects boards)": (
        "world", (broken(SHARED, EVICTED_NEEDS_WORK, "    void 0;"),),
        test_an_abandoned_board_start_with_nothing_typed_never_becomes_a_row),
    "a blob nobody typed into is flushed when another project opens (the v2 board)": (
        "world", (broken(SHARED, EVICTED_NEEDS_WORK, "    void 0;"),),
        test_an_abandoned_v2_start_never_becomes_a_nameless_row),
    # ── round 4, F5: another project's blob is never saved under this project's id ──
    "the sandbox does not stop on a blob stamped for another project": (
        "world", (broken(SANDBOX, SANDBOX_FOREIGN_STOP, "    if (false) {"),),
        test_a_v2_page_whose_shared_blob_belongs_to_another_project_stops_and_saves_nothing),
    "the sandbox's save writes another project's blob under this project's id": (
        "world", (broken(SANDBOX, SANDBOX_FOREIGN_SAVE, "    if (false) {"),),
        test_a_save_made_for_one_project_never_carries_another_projects_blob),
    # ── round 4, F6: the size of a save sent as the page goes is counted in bytes ──
    "a three-byte character is counted as one byte": (
        "world", (broken(SHARED, KEEPALIVE_THREE_BYTES, "      else bytes += 1;"),),
        test_a_draft_under_the_keepalive_limit_in_characters_and_over_it_in_bytes_goes_as_a_plain_request),
    "a two-byte character is counted as one byte": (
        "world", (broken(SHARED, KEEPALIVE_TWO_BYTES, "      else if (c < 0x800) bytes += 1;"),),
        test_a_draft_under_the_keepalive_limit_in_characters_and_over_it_in_bytes_goes_as_a_plain_request),
    "a four-byte character is counted as two bytes": (
        "world", (broken(SHARED, KEEPALIVE_FOUR_BYTES, KEEPALIVE_FOUR_BYTES.replace("bytes += 4;", "bytes += 2;")),),
        test_a_draft_under_the_keepalive_limit_in_characters_and_over_it_in_bytes_goes_as_a_plain_request),
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
    for must in (test_a_new_project_is_born_filed_whichever_way_it_leaves,
                 test_the_first_save_says_what_the_project_was_started_as,
                 test_the_start_is_said_by_the_first_write_that_has_content_and_only_for_its_own_project,
                 test_every_other_door_out_of_the_intake_leaves_one_row_born_filed,
                 test_the_next_new_estimate_does_not_leave_the_first_one_behind,
                 test_whatever_the_latencies_the_new_project_is_born_filed_and_never_forked,
                 test_a_stale_tab_cannot_undo_a_humans_filing,
                 test_a_server_that_never_answers_does_not_trap_the_estimator,
                 test_a_save_that_fails_at_once_is_not_waited_out,
                 test_nothing_depends_on_a_filing_request,
                 test_a_save_that_fails_once_still_ends_born_filed,
                 test_a_save_that_cannot_be_made_is_said_and_never_claimed_as_a_filing,
                 test_a_new_project_that_could_not_be_saved_as_the_page_opened_is_still_created_filed,
                 test_the_next_page_boots_while_a_filing_never_answers,
                 test_continue_tells_the_estimator_it_is_saving,
                 test_continue_gives_the_button_back_when_the_browser_does_not_go,
                 test_continue_says_it_is_saving_and_ignores_a_second_press_on_the_page_alone,
                 test_continue_gives_the_button_back_on_the_page_alone,
                 test_continue_leaves_when_the_wait_is_over_however_it_ends,
                 test_a_stale_start_for_a_project_that_has_moved_on_is_copied_and_never_filed,
                 test_the_record_of_what_the_server_holds_is_written_as_the_first_save_is_stored,
                 test_a_project_started_from_the_test_tab_is_born_filed_through_the_live_intake,
                 test_a_project_started_from_the_active_tab_is_born_as_a_real_bid,
                 test_all_and_inactive_start_a_project_that_nobody_has_said_anything_about,
                 test_the_projects_page_hands_the_live_intake_the_tab_it_started_from,
                 test_a_real_project_is_copied_never_filed_and_never_written_to,
                 test_a_real_project_is_copied_and_never_written_to_or_filed,
                 test_a_real_bid_saved_in_the_live_intake_is_never_flagged,
                 # round 3
                 test_a_look_at_a_v2_page_starts_nothing_and_changes_nothing,
                 test_the_active_tabs_real_bid_is_not_made_a_test_by_a_look_at_v2,
                 test_a_project_typed_into_on_a_v2_page_is_a_test_project_whichever_tab_started_it,
                 test_a_gc_boards_active_start_is_not_filed_as_a_test_by_a_look_at_v2,
                 test_an_abandoned_board_blob_that_holds_work_is_flushed_born_as_its_tab_said,
                 test_a_copy_that_already_says_is_test_is_sent_as_it_is,
                 test_a_start_whose_flush_was_refused_stays_armed_for_the_next_save,
                 test_two_tabs_each_start_their_own_project_and_keep_their_own_start,
                 test_every_door_out_of_the_intake_leaves_a_row_even_inside_the_debounce,
                 test_a_save_sent_as_the_page_goes_is_never_a_keepalive_request_the_browser_refuses,
                 test_a_v2_pages_own_word_is_said_by_the_first_write_it_makes_and_only_by_that,
                 test_new_project_mints_the_projects_id_with_its_own_start,
                 test_a_blob_with_nothing_in_it_is_sent_as_it_is,
                 test_a_start_is_spent_when_the_server_has_stored_a_copy_that_carries_it_and_not_before,
                 test_another_tabs_new_project_cannot_empty_the_save_this_page_has_queued,
                 test_the_queued_save_never_writes_another_projects_blob_under_this_projects_id,
                 test_a_v2_page_opened_on_a_project_nobody_had_written_does_not_make_it_a_test_once_somebody_has,
                 # round 4
                 test_leaving_with_two_saves_pending_sends_one_save_carrying_the_newest_edit,
                 test_the_beta_door_waits_for_the_project_to_be_saved_before_it_opens_the_v2_intake,
                 test_the_beta_door_says_it_is_saving_ignores_a_second_press_and_is_given_back,
                 test_the_beta_door_leaves_when_its_wait_is_over_however_it_ends,
                 test_an_abandoned_board_start_with_nothing_typed_never_becomes_a_row,
                 test_the_v2_boards_new_estimate_starts_the_project_as_a_test_under_its_own_id,
                 test_an_abandoned_v2_start_never_becomes_a_nameless_row,
                 test_a_project_started_on_the_v2_board_is_a_test_whichever_page_writes_it_first,
                 test_a_v2_page_opened_by_a_bare_link_on_a_project_nobody_started_says_test_in_its_own_first_write,
                 test_a_v2_page_whose_shared_blob_belongs_to_another_project_stops_and_saves_nothing,
                 test_a_save_made_for_one_project_never_carries_another_projects_blob,
                 test_a_draft_under_the_keepalive_limit_in_characters_and_over_it_in_bytes_goes_as_a_plain_request):
        assert must.__name__ in named, "no break turns %s red" % must.__name__


def test_every_anchor_a_break_uses_is_still_one_line_of_its_file():
    """The anchors are lines of the real sources, and a break_source run would refuse one that moved. This says it
    without running a harness: every entry's anchor is a single line, found exactly once, in the file it names."""
    for name, (_which, edits, _check) in sorted(BREAKS.items()):
        for rel, old, _new in edits:
            src = (FRONTEND / rel).read_bytes().decode("utf-8")
            assert "\n" not in old and "\r" not in old, name
            assert src.count(old) == 1, "%s: %r is in %s %d times" % (name, old, rel, src.count(old))
