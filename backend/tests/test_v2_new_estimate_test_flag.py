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

HOW THESE TESTS RUN. tests/js/new-estimate-test-flag-harness.js runs the REAL shared.js, js/polish-sandbox.js,
js/polish-intake.js and js/index.js, whole, in tests/js/_world.js: a browser model with virtual time in which a page's
timers and replies die with it and a keepalive request survives it with nobody to hear the answer. The intake is driven as
a person drives it; every fact is read off the server's rows (what each was BORN as, and what it is now) and the pages after
everything has settled. The model's browser rules and its server are held to the real thing by the first tests below.
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
              "js/projects.js", "js/work-types.js", "js/intake-scope.js", "js/bid-model.js", "js/excel-math.js"]
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


def test_the_projects_page_hands_the_live_intake_the_tab_it_started_from(ran):
    """The harness runs the REAL click handler of js/projects.js (lifted out of the file) and then the live intake's
    own shared.js: "+ New project" on Test leaves "<id>:1" bound to the id the intake minted, on Active "<id>:0", and on All
    nothing. The v1 flows below start from exactly this."""
    v1 = ran["v1"]
    assert v1["test"]["intentOnArrival"] == v1["test"]["id"] + ":1", "Test: %r" % v1["test"]["intentOnArrival"]
    assert v1["active"]["intentOnArrival"] == v1["active"]["id"] + ":0", "Active: %r" % v1["active"]["intentOnArrival"]
    assert v1["all"]["intentOnArrival"] is None, "All: %r" % v1["all"]["intentOnArrival"]


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


def test_the_first_save_says_what_the_project_was_started_as(ran):
    """WHY it works, on the wire. The project's FIRST PUT (the autosave's, Continue's, the pagehide keepalive's, the estimate
    page's, whichever goes first) carries is_test in its body: true for a project started as a test, false for one started
    from the Active tab, and nothing for All. And the start is used up by that first write, so nothing is left armed in the
    one localStorage slot to file some other project (or this one, later) by mistake."""
    for flow in ("fast", "fastAfterAutosave", "slow"):
        r = ran[flow]
        first = reqs(r, "PUT", r["id"])[0]
        assert first["sentIsTest"] is True, "%s: the first save did not say the project is a test: %r" % (flow, first)
        assert r["intent"] is None, "%s: the start was not used up by the first write (%r)" % (flow, r["intent"])
    v1 = ran["v1"]
    assert reqs(v1["test"], "PUT", v1["test"]["id"])[0]["sentIsTest"] is True
    assert reqs(v1["active"], "PUT", v1["active"]["id"])[0]["sentIsTest"] is False
    assert reqs(v1["all"], "PUT", v1["all"]["id"])[0]["sentIsTest"] is None


def test_the_start_is_said_once_by_the_first_write_that_has_content_and_only_for_its_own_project(ran):
    """shared.js's stamp, executed on its own. A start for THIS project is said in the blob by the first write that holds
    anything, and the slot is emptied by it: true for a test, false for a real bid. A write that holds nothing yet (an empty
    partial on a project nobody has typed into) says nothing and leaves the start where it is, so an untouched project stays
    a blob with nothing in it and never becomes a row. A blob that already says is_test (a human's word, written by a
    hydrate) is not overruled, and the start is used up all the same. A start for ANOTHER project, or an unbound one, is not
    applied here and not used up. And a second write has nothing left to say."""
    s = ran["stampRules"]
    assert s["test"]["blob"].get("is_test") is True and s["test"]["slot"] is None, s["test"]
    assert s["real"]["blob"].get("is_test") is False and s["real"]["slot"] is None, s["real"]
    assert "is_test" not in s["empty"]["blob"] and s["empty"]["slot"] == s["empty"]["id"] + ":1", s["empty"]
    assert set(s["empty"]["blob"]) <= {"__draft_id"}, "an empty write made the project non-empty: %r" % s["empty"]["blob"]
    assert s["emptyThenContent"]["blob"].get("is_test") is True and s["emptyThenContent"]["slot"] is None, s["emptyThenContent"]
    assert s["says"]["blob"].get("is_test") is False and s["says"]["slot"] is None, s["says"]
    assert "is_test" not in s["other"]["blob"] and s["other"]["slot"] == "someone-else:1", s["other"]
    assert "is_test" not in s["unbound"]["blob"] and s["unbound"]["slot"] == "1", s["unbound"]
    assert s["later"]["blob"].get("is_test") is True and s["later"]["blob"]["project_name"] == "B" and s["later"]["slot"] is None, s["later"]


def test_every_other_door_out_of_the_intake_leaves_one_row_born_filed(ran):
    """The audit's F2. The "2 · Estimate" step link, Back (to the Projects page), a closed tab and a reload, at 0.1, 0.6, 0.7,
    1.5, 3.0, 3.1 and 3.2 s after the last edit (before the page's own 600 ms save, between it and the 2.5 s timer that sends
    it, and across the moment the autosave PUT goes). None of them waits for anything, so each sends whatever it sends as the
    page goes (a plain request that dies with the page, or a keepalive one whose reply nobody sees).

    Whatever reached the server was born FILED: no row is ever on the board unfiled, nothing is forked, and there is
    never a second row. Where the estimator went to the estimate page it is on the project, editing it directly; where
    they did not (Back, a closed tab) the project is reopened a minute later in the v2 intake and is filed, directly
    editable and still the only row, whether the first leg left a row (a keepalive PUT) or none (a plain one dropped).

    Not vacuous: both legs occur in the matrix (a closed tab that left a row, and one that left none), and so do all
    four doors at all seven times."""
    exits = ran["exits"]
    assert len(exits) == 28 and {(e["door"], e["waitMs"]) for e in exits} == {
        (d, w) for d in ("link", "back", "close", "reload") for w in (100, 600, 700, 1500, 3000, 3100, 3200)}
    left_a_row, left_none = 0, 0
    for r in exits:
        flow = "%s at %d ms" % (r["door"], r["waitMs"])
        assert_born_filed(r, flow)
        if r["door"] == "link":
            est = r["estimate"] or {}
            assert est.get("settled") is True and est.get("draftId") == r["id"] and DIRECT in says(r) and COPY not in says(r), (
                "%s: %s" % (flow, describe(r)))
            continue
        before = r["before"]
        if before["x"] is None:
            left_none += 1
        else:
            left_a_row += 1
            assert before["x"]["bornIsTest"] is True and before["x"]["is_test"] is True, (
                "%s: the row the closed tab left behind was unfiled: %r" % (flow, before["x"]))
        assert before["beta"] is None
        assert r["intakeDraft"] == r["id"] and DIRECT in r["intakeNote"] and COPY not in r["intakeNote"], (
            "%s: the reopened project is not edited directly: %r %r" % (flow, r["intakeDraft"], r["intakeNote"]))
    assert left_a_row >= 12 and left_none >= 2, (left_a_row, left_none)


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
    assert r["blob"].get("is_test") is True and r["x"]["bornIsTest"] is True


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
    index.js saves it), its address changed and Continue pressed, with something else in the one localStorage slot: nothing at
    all; ANOTHER project's start (which is neither applied to this one nor used up); and the bare "1" that a "+ New project" on
    the Test tab leaves behind when it is abandoned (which arriving at an existing project drops). The bid is saved, as itself:
    no is_test in what was sent, none on the row, no filing request, and the one row there is."""
    for name, slot in (("clean", None), ("anotherStart", "other-1:1"), ("abandonedNew", None)):
        r = ran["v1Real"][name]
        assert r["x"] == {"is_test": None, "bornIsTest": None, "flips": 0, "beta_sandbox_of": None,
                          "project_name": "Nearman Creek Epoxy"}, (name, r["x"])
        assert r["address"] == "9 New Address" and r["draftOnIntake"] == "sheet-3", "%s: the bid was not saved as itself: %r" % (name, r["address"])
        puts = reqs(r, "PUT", "sheet-3")
        assert puts and [p["sentIsTest"] for p in puts] == [None] * len(puts), "%s: a save said is_test: %r" % (name, puts)
        assert reqs(r, "TEST") == [] and r["rowIds"] == ["sheet-3"], (name, r["rowIds"])
        assert r["intent"] == slot and r["intentBeforeContinue"] == slot, "%s: the slot is %r, expected %r" % (name, r["intent"], slot)


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


# (run, what the real row's is_test is, what is left pending in storage)
REAL_CASES = [
    ("realProject", None, None),
    ("anotherProjects", None, "other-1:1"),
    ("saidReal", False, REAL_PROJECT + ":1"),
    ("filingAsReal", None, REAL_PROJECT + ":0"),
]


def test_a_real_project_is_copied_never_filed_and_never_written_to(ran):
    """THE RULE NOTHING MAY BREAK. A project nobody here made as a new test project, whatever else is in storage, is a real
    bid: the sandbox copies it as it always did, files the copy, and never writes to the real row.
      realProject      nothing pending at all
      anotherProjects  ANOTHER project's start is pending: it is neither used nor lost
      saidReal         a human filed this one as a real bid (is_test false) and a start for it is still pending
      filingAsReal     the pending start says "real" ("<id>:0", the Active tab's New project), not "test"
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
        assert r["intent"] == pending, "%s: the pending start was used up or changed: %r, was %r" % (scenario, r["intent"], pending)


def test_a_copy_is_edited_directly_and_nothing_is_filed_for_it(ran):
    """A test copy whose own start is somehow pending (it never is: nothing writes one for a copy) is still what it
    always was to the sandbox: edited directly, with nothing sent for it."""
    r = ran["aCopy"]
    assert r["x"] == {"is_test": None, "bornIsTest": None, "flips": 0, "beta_sandbox_of": "some-real-project",
                      "project_name": "Wichita Warehouse (beta test)"}, r["x"]
    assert [q for q in reqs(r, id_=REAL_PROJECT) if q["method"] != "GET"] == [], "something was sent for a copy"
    assert (r["estimate"] or {}).get("draftId") == REAL_PROJECT and DIRECT in says(r), describe(r)
    assert r["intent"] == REAL_PROJECT + ":1"


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


def test_the_two_places_that_name_the_pending_start_agree():
    """shared.js owns the pending start and the sandbox's markNewProjectAsTest writes it. Two spellings of one key: if they
    drift apart the start is written where nothing reads it, and a new test project is quietly created unfiled (the runs above
    would still be red, but for a reason nobody could see in the diff)."""
    shared = (FRONTEND / "shared.js").read_text(encoding="utf-8")
    sandbox = _sandbox_code()
    keys = {
        "shared.js NEW_IS_TEST_KEY": re.search(r'const NEW_IS_TEST_KEY = "([^"]+)";', shared).group(1),
        "markNewProjectAsTest": re.search(r'function markNewProjectAsTest\(id\) \{\s*try \{ localStorage\.setItem\("([^"]+)", id \+ ":1"\)',
                                          sandbox).group(1),
    }
    assert len(set(keys.values())) == 1 and INTENT_KEY in keys.values(), keys


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

# shared.js: the stamp, its rules and the two places a start is bound
STAMP_CALL = "    if (id) sayWhatItWasStartedAs(id, merged);   // a NEW project's first write says what it was started as"
STAMP_CONTENT = '    if (!Object.keys(blob).some((k) => k !== STAMP && k !== "is_test")) return;'
STAMP_USE_UP = "    try { localStorage.removeItem(NEW_IS_TEST_KEY); } catch {}"
STAMP_KEEPS_A_WORD = '    if (!Object.prototype.hasOwnProperty.call(blob, "is_test")) blob.is_test = want;'
STAMP_NONE_PENDING = "    if (want === null) return;"
STAMP_THIS_ID = "      if (i < 0 || raw.slice(0, i) !== id) return null;"
SYNCED_LINE = "        if (ok && id === getDraftId() && getState()[STAMP] === id) markSynced(id, sent);"
BIND_AT_MINTING = "      if (minting) bindNewProjectTestIntent(getDraftId());"
BIND_WRITES = '      if (raw === "1" || raw === "0") localStorage.setItem(NEW_IS_TEST_KEY, id + ":" + raw);'
# the sandbox
SANDBOX_SAYS_TEST = "      body: JSON.stringify({ data: Object.assign({}, blob, { is_test: true }) }),"
SANDBOX_NOTE_UNSAVED = "          showUnsavedNote();"
SANDBOX_REARMS = "          markNewProjectAsTest(id);"
SANDBOX_IF_SAVED = "        if (saved) {"
SANDBOX_SAVES = "        try { await saveThenFileAsTest(id, state); }"
SANDBOX_SAVE_FN = "  async function saveThenFileAsTest(id, blob) {"
SANDBOX_EXACT_TRISTATE = "    if (row.is_test === true || row.beta_sandbox_of) {"
MARK_LINE = '    try { localStorage.setItem("treadwell.proposal_tool.new_is_test", id + ":1"); } catch (e) {}'
# the intake
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
# the Projects page
ACTIVE_TAB = '        else if (CURRENT_FILTER === "active") TW.setNewProjectTestIntent(false);'
OTHER_TABS = "        else                                  TW.setNewProjectTestIntent(null);"


def broken(rel, old, new):
    return (rel, old, new)


def every(test, modes):
    """A parametrized test as one check over all its parameters, under the test's own name."""
    def check(ran):
        for mode in modes:
            test(ran, mode)
    check.__name__ = test.__name__
    return check


FILING_MODES = ("http500", "okfalse", "network", "hang", "html", "gone")
SAVE_MODES = ("http500", "okfalse", "network")
check_nothing_depends_on_a_filing_request = every(test_nothing_depends_on_a_filing_request, FILING_MODES)
check_a_save_that_fails_once = every(test_a_save_that_fails_once_still_ends_born_filed, SAVE_MODES)
check_a_save_that_cannot_be_made = every(test_a_save_that_cannot_be_made_is_said_and_never_claimed_as_a_filing, SAVE_MODES)

# name -> (harness, (the lines to break: (file, anchor line, what it becomes), ...), the check)
BREAKS = {
    # ── the seed: setState says what the project was started as ──
    "no write says what the project was started as (every flow)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_a_new_project_is_born_filed_whichever_way_it_leaves),
    "no write says what the project was started as (the first save, on the wire)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_the_first_save_says_what_the_project_was_started_as),
    "no write says what the project was started as (every other door)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_every_other_door_out_of_the_intake_leaves_one_row_born_filed),
    "no write says what the project was started as (the next new estimate)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_the_next_new_estimate_does_not_leave_the_first_one_behind),
    "no write says what the project was started as (the latencies)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_whatever_the_latencies_the_new_project_is_born_filed_and_never_forked),
    "no write says what the project was started as (a /test that goes wrong)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), check_nothing_depends_on_a_filing_request),
    "no write says what the project was started as (a save that fails once)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), check_a_save_that_fails_once),
    "no write says what the project was started as (a stale tab)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_a_stale_tab_cannot_undo_a_humans_filing),
    "no write says what the project was started as (the live intake)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_a_project_started_from_the_test_tab_is_born_filed_through_the_live_intake),
    "no write says what the project was started as (a save that cannot be made at all)": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_a_new_project_that_could_not_be_saved_as_the_page_opened_is_still_created_filed),
    "a server that never answers: the first save says nothing": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_a_server_that_never_answers_does_not_trap_the_estimator),
    "a save that fails at once: the first save says nothing": (
        "world", (broken(SHARED, STAMP_CALL, "    void 0;"),), test_a_save_that_fails_at_once_is_not_waited_out),
    "a pending start written without the project's id, so nothing can find it": (
        "world", (broken(SANDBOX, MARK_LINE,
                         '    try { localStorage.setItem("treadwell.proposal_tool.new_is_test", "1"); } catch (e) {}'),),
        test_a_new_project_is_born_filed_whichever_way_it_leaves),
    # ── the stamp's own rules ──
    "an empty write says it and uses the start up": (
        "world", (broken(SHARED, STAMP_CONTENT, "    void 0;"),),
        test_the_start_is_said_once_by_the_first_write_that_has_content_and_only_for_its_own_project),
    "the start is not used up by the write that says it": (
        "world", (broken(SHARED, STAMP_USE_UP, "    void 0;"),),
        test_the_start_is_said_once_by_the_first_write_that_has_content_and_only_for_its_own_project),
    "the start is not used up (on the wire)": (
        "world", (broken(SHARED, STAMP_USE_UP, "    void 0;"),), test_the_first_save_says_what_the_project_was_started_as),
    "a start overrules a blob that already says is_test": (
        "world", (broken(SHARED, STAMP_KEEPS_A_WORD, "    blob.is_test = want;"),),
        test_the_start_is_said_once_by_the_first_write_that_has_content_and_only_for_its_own_project),
    "a write says something even when no start is pending": (
        "world", (broken(SHARED, STAMP_NONE_PENDING, "    if (want === undefined) return;"),),
        test_the_start_is_said_once_by_the_first_write_that_has_content_and_only_for_its_own_project),
    "another project's start is applied to this one": (
        "world", (broken(SHARED, STAMP_THIS_ID, "      if (i < 0) return null;"),),
        test_the_start_is_said_once_by_the_first_write_that_has_content_and_only_for_its_own_project),
    "another project's start files a real bid saved in the live intake": (
        "world", (broken(SHARED, STAMP_THIS_ID, "      if (i < 0) return null;"),),
        test_a_real_bid_saved_in_the_live_intake_is_never_flagged),
    "a real bid's write uses up another project's start": (
        "world", (broken(SHARED, STAMP_NONE_PENDING, "    if (want === undefined) return;"),),
        test_a_real_bid_saved_in_the_live_intake_is_never_flagged),
    # ── the sandbox: a save that creates a project as a test, and says so honestly ──
    "the sandbox's save does not say is_test (the page that creates the project)": (
        "world", (broken(SANDBOX, SANDBOX_SAYS_TEST, "      body: JSON.stringify({ data: blob }),"),),
        test_a_new_project_is_born_filed_whichever_way_it_leaves),
    "the sandbox's save does not say is_test (the copy)": (
        "world", (broken(SANDBOX, SANDBOX_SAYS_TEST, "      body: JSON.stringify({ data: blob }),"),),
        test_a_real_project_is_copied_never_filed_and_never_written_to),
    "the sandbox never saves the project it says it saved": (
        "world", (broken(SANDBOX, SANDBOX_SAVES, "        try { void 0; }"),),
        test_a_new_project_is_born_filed_whichever_way_it_leaves),
    "a save that failed is said to be filed": (
        "world", (broken(SANDBOX, SANDBOX_IF_SAVED, "        if (true) {"),), check_a_save_that_cannot_be_made),
    "a save that failed is not said at all": (
        "world", (broken(SANDBOX, SANDBOX_NOTE_UNSAVED, "          showDirectNote(false);"),), check_a_save_that_cannot_be_made),
    "a save that failed does not arm the start again": (
        "world", (broken(SANDBOX, SANDBOX_REARMS, "          void 0;"),),
        test_a_new_project_that_could_not_be_saved_as_the_page_opened_is_still_created_filed),
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
    "a new project's start is never bound to the id the live intake mints": (
        "world", (broken(SHARED, BIND_AT_MINTING, "      void 0;"),),
        test_a_project_started_from_the_test_tab_is_born_filed_through_the_live_intake),
    "a new project's start is never bound (what the Projects page hands over)": (
        "world", (broken(SHARED, BIND_AT_MINTING, "      void 0;"),),
        test_the_projects_page_hands_the_live_intake_the_tab_it_started_from),
    "the Active tab's start is bound as a test": (
        "world", (broken(SHARED, BIND_WRITES, '      if (raw === "1" || raw === "0") localStorage.setItem(NEW_IS_TEST_KEY, id + ":1");'),),
        test_a_project_started_from_the_active_tab_is_born_as_a_real_bid),
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
                 test_the_start_is_said_once_by_the_first_write_that_has_content_and_only_for_its_own_project,
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
                 test_a_real_project_is_copied_and_never_written_to_or_filed):
        assert must.__name__ in named, "no break turns %s red" % must.__name__


def test_every_anchor_a_break_uses_is_still_one_line_of_its_file():
    """The anchors are lines of the real sources, and a break_source run would refuse one that moved. This says it
    without running a harness: every entry's anchor is a single line, found exactly once, in the file it names."""
    for name, (_which, edits, _check) in sorted(BREAKS.items()):
        for rel, old, _new in edits:
            src = (FRONTEND / rel).read_bytes().decode("utf-8")
            assert "\n" not in old and "\r" not in old, name
            assert src.count(old) == 1, "%s: %r is in %s %d times" % (name, old, rel, src.count(old))
