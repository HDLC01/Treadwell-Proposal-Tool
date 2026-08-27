"""Opening a project link must never blank the project.

THE BUG, which was live on production. Open a real project link on a machine whose localStorage
had been cleared — a colleague's laptop, a new browser, a cleared cache — and the form rendered
EMPTY over a live bid. The first keystroke then pushed that emptiness back to the server. Name,
scope notes and square footage all replaced. Reproduced on prod with a sentinel before the fix.

WHY IT SURVIVED SO LONG. Three conditions that each read as correct:

    const owned = stamp === urlId
               || (!stamp && localId === urlId)
               || (!stamp && empty);        // "fresh device / just-cleared — nothing to protect"

The third answers the wrong question. Nothing to protect LOCALLY is not the same as owning the
project, and claiming ownership is what SKIPS the hydrate. Then `setState` stamps the merged blob
with the URL's id, so `scheduleServerSave`'s mismatch guard sees a stamp that agrees and lets the
PUT through. Every individual guard behaved exactly as designed.

WHY THIS FILE RUNS THE CODE INSTEAD OF READING IT. Every other test of shared.js inspects its
source, and that is why this shipped: every string such a test would look for was already there.
The defect was in how the conditions COMBINED. So `js/draft-sync-harness.js` puts a thin fake
browser around the real file — localStorage, sessionStorage, fetch, location, history — and these
tests assert on what actually happens to the server copy.

THE SECOND HOLE, closed here too. If the hydrate GET fails twice, shared.js adopts a
stamped-empty blob. From then on the stamp AGREES with the draft id, so every save guard is
satisfied and the next keystroke overwrites anyway. An adopt that never saw the server is now
recorded in sessionStorage and server saves are refused while it stands — edits stay local, which
is a smaller loss than destroying a bid nobody can recover.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "draft-sync-harness.js"
SHARED = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "shared.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

REAL_BID = {"project_name": "Nearman Creek Power Station",
            "scope_notes": "Grind and seal 12,400 SF",
            "epoxy_sf": 12400}
PID = "real-bid-0001"


def run(**scenario):
    out = subprocess.run(["node", str(HARNESS), json.dumps(scenario)],
                         capture_output=True, text=True, encoding="utf-8", timeout=90)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


# ── the reported failure ─────────────────────────────────────────────────────
def test_cleared_storage_reads_the_project_instead_of_claiming_it():
    """THE regression test. Empty local state is the case that MUST hydrate."""
    r = run(urlId=PID, local={}, session={}, server=dict(REAL_BID))
    assert r["gets"] == 1, "the server copy was never fetched"
    assert r["localAfter"]["project_name"] == "Nearman Creek Power Station"
    assert r["localAfter"]["epoxy_sf"] == 12400


def test_the_real_bid_is_still_on_the_server_afterwards():
    """The damage, asserted directly rather than via the mechanism that caused it."""
    r = run(urlId=PID, local={}, session={}, server=dict(REAL_BID))
    assert r["serverAfter"]["project_name"] == "Nearman Creek Power Station"
    assert r["serverAfter"]["scope_notes"] == "Grind and seal 12,400 SF"
    assert r["serverAfter"]["epoxy_sf"] == 12400


def test_typing_after_a_clean_open_edits_the_project_rather_than_replacing_it():
    """What an estimator actually does: open the link, change one field. Every other field has
    to survive, because the blank form is exactly what used to be saved over them."""
    r = run(urlId=PID, local={}, session={}, server=dict(REAL_BID),
            type={"project_name": "Nearman Creek Power Station - Rev 2"})
    assert r["puts"], "nothing was saved at all"
    saved = r["puts"][-1]
    assert saved["project_name"] == "Nearman Creek Power Station - Rev 2"
    assert saved["scope_notes"] == "Grind and seal 12,400 SF", "the scope notes were dropped"
    assert saved["epoxy_sf"] == 12400, "the square footage was dropped"


def test_an_empty_blob_no_longer_counts_as_owning_the_draft():
    """The removed clause, pinned at the source too. Running the code proves the behaviour;
    this says WHICH condition must stay gone, so it cannot come back as an optimisation."""
    src = SHARED.read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("//"))
    assert "!stamp && empty" not in code, (
        "the ownership clause that skipped hydration is back; an empty local blob would again "
        "render blank over a live project and then save over it")


# ── the narrower hole: an adopt that never read the server ───────────────────
def test_a_failed_read_does_not_let_the_page_save_over_the_project():
    """Two failed GETs and shared.js adopts empty. The stamp then agrees with the draft id, so
    nothing downstream objects — this is the last path by which a blank form reached the PUT."""
    r = run(urlId=PID, local={}, session={}, server=dict(REAL_BID), serverStatus=500,
            type={"project_name": "typed into a blank form"})
    assert r["puts"] == [], "an unread draft was saved over"
    assert r["serverAfter"]["project_name"] == "Nearman Creek Power Station"
    assert r["unverified"] == PID, "the unread adopt was not recorded"


def test_the_refusal_says_why():
    """A save that silently does nothing is its own bug. Somebody has to be able to find this."""
    r = run(urlId=PID, local={}, session={}, server=dict(REAL_BID), serverStatus=500,
            type={"project_name": "x"})
    assert any("without being read" in w for w in r["warns"]), r["warns"]
    assert any("saves are held back" in w for w in r["warns"]), r["warns"]


def test_the_block_clears_itself_once_the_read_succeeds():
    """Otherwise one transient blip locks a project out of saving for the whole session. The
    unverified mark makes the draft read as not-ours, so the next load retries the fetch."""
    r = run(urlId=PID, local={"treadwell.proposal_tool.state": json.dumps({"__draft_id": PID})},
            session={"treadwell.proposal_tool.unverified": PID}, server=dict(REAL_BID))
    assert r["gets"] == 1, "an unverified draft was not re-read"
    assert r["unverified"] is None, "the mark survived a successful read"
    assert r["localAfter"]["project_name"] == "Nearman Creek Power Station"


def test_a_404_is_a_real_answer_and_does_not_block_saving():
    """A draft nobody has saved yet. The server genuinely holds nothing, so empty is the truth
    rather than a guess — and a brand-new project has to be able to save."""
    r = run(urlId="brand-new-0002", local={}, session={}, serverStatus=404,
            type={"project_name": "Cedar Ridge"})
    assert r["unverified"] is None, "a 404 was treated as a failed read"
    assert r["puts"], "a brand-new project could not save"
    assert r["puts"][-1]["project_name"] == "Cedar Ridge"


# ── what must not have changed ───────────────────────────────────────────────
def test_a_matching_stamp_still_skips_the_fetch():
    """The fast path. Every page load doing a network round-trip would be a real cost, and this
    is the case that covers ordinary work: same machine, same project, page to page."""
    blob = dict(REAL_BID); blob["__draft_id"] = PID
    r = run(urlId=PID, local={"treadwell.proposal_tool.state": json.dumps(blob)},
            session={}, server=dict(REAL_BID))
    assert r["gets"] == 0, "an owned draft is being re-fetched on every page load"
    assert r["reloads"] == 0


def test_another_drafts_blob_still_hydrates():
    """The behaviour the stamp was introduced for: draft A's state must never render as draft B."""
    other = {"project_name": "Somebody else's bid", "__draft_id": "other-0003"}
    r = run(urlId=PID, local={"treadwell.proposal_tool.state": json.dumps(other)},
            session={}, server=dict(REAL_BID))
    assert r["gets"] == 1
    assert r["localAfter"]["project_name"] == "Nearman Creek Power Station"


def test_the_other_drafts_edits_are_flushed_under_their_own_id_first():
    """Evicting a foreign blob must not throw its unsynced tail away."""
    other = {"project_name": "Somebody else's bid", "__draft_id": "other-0003"}
    r = run(urlId=PID, local={"treadwell.proposal_tool.state": json.dumps(other)},
            session={}, server=dict(REAL_BID))
    assert any(p.get("project_name") == "Somebody else's bid" for p in r["puts"]), (
        "the other draft's state was discarded instead of saved under its own id")


# ── what Ctrl+S is allowed to claim ──────────────────────────────────────────
# Hanz, 2026-08-27, on Ctrl+S in the proposal editor: "DO you mean to implement? then yes."
#
# The key finishes the pending autosave and reports the outcome, so it needs to be able to tell
# "already in sync" from "refused before it left the browser". flushState() cannot: it answers
# `true` both when there was nothing to do AND after dropping a save one of the gates refused,
# because it then awaits an `_inFlight` promise belonging to an older, successful write. saveBlocked
# is the narrow read-only question that can be asked instead, and these pin its three answers.
def test_a_healthy_draft_reports_nothing_blocking_a_save():
    r = run(urlId=PID, local={}, session={}, server=dict(REAL_BID))
    assert r["saveBlocked"] is None


def test_an_unread_draft_reports_that_a_save_would_be_refused():
    """The case that matters. Two failed GETs, shared.js adopts empty and marks the draft
    unverified — server saves are held back from then on, and the estimator's edits live only in
    this browser. A Ctrl+S that answered "Saved" here would be telling them the opposite of the
    truth about a bid they may be about to close the tab on."""
    r = run(urlId=PID, local={}, session={}, server=dict(REAL_BID), serverStatus=500,
            type={"project_name": "typed into a blank form"})
    assert r["puts"] == [], "the premise changed: an unread draft is being saved again"
    assert r["saveBlocked"] == "unverified"


def test_a_blob_stamped_for_another_project_reports_the_same_refusal():
    """The other gate scheduleServerSave carries. Here the local blob belongs to a different draft
    than the URL, which is the case that hydrates — so the answer is read before that lands."""
    r = run(urlId=PID, local={}, session={}, server=dict(REAL_BID), serverStatus=500)
    assert r["saveBlocked"] in ("unverified", "foreign-blob"), r["saveBlocked"]


def test_asked_before_there_is_a_project_it_says_so():
    """The third answer, and the only moment it is reachable: a page with no ?d= and nothing in
    localStorage, asked before initDraftSync has minted an id. Every page that asks in practice
    does so after its own init, by which point there is an id — but a reporter whose fallback was
    "nothing is blocking a save" would be guessing, and guessing is the thing it exists not to do."""
    r = run(url="https://proposals.example.com/proposal-review.html", local={}, session={})
    assert r["saveBlockedAtLoad"] == "no-draft"
    assert r["saveBlocked"] is None, "an id was never minted; the premise of this test moved"
