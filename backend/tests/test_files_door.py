"""Every way into the Files step rebuilds the proposal from the draft as it stands.

Hanz, 2026-09-25: "Clicking to Done should regenerate and make the proposal correctly", and "When
creating a revision and sending out to the portal ... it doesnt show the correct proposal. This
happens when they change something or revise something and send it out again."

The Files page's Download and Send are both built from the SAVED `proposal_payload` (fix 3), and
only the Proposal step's Continue composed one. So a texture picked on the Estimate step, a
re-price, a note, the tax mode or a base flip reached Files by any other route — a step pill from
Intake or Estimate, the Polish beta's Files link, View files off the board, a reload, a typed URL —
with the document from the LAST Continue, and that is what the customer was sent.

THE DESIGN, and why not a second composer. The composition needs the Proposal step's own machinery
(computeTokenValues, the editor's paragraph and box edits read off the mounted template, the WORK
system picks), so rather than a second copy of it on the Files page, the Files page has ONE DOOR:
continueToDone stamps the draft with TW.composeKey (a hash of the inputs, and of the document) as
it writes, the Files page checks the key on arrival, and a draft whose document is not current is
sent through the Proposal step with `?compose=files`, which presses Continue for it once the page
has settled and comes straight back. A document that IS current is left alone and nothing is
written.

THE SERVER'S COPY DECIDES, never an older one in this browser (review of the door, 2026-09-25).
initDraftSync keeps a localStorage copy already stamped for the draft without re-reading the
server, so this browser can hold a copy older than a colleague's revision, or than Troy marking the
job Won. The door used to build from that copy and PUT the whole of it back. Now the Files page asks
the server first (TW.reconcileWithServer): a local copy with nothing the server lacks is replaced
by the server's; one that is the server's plus edits whose save never landed ("ahead") is built and
saved; one where BOTH sides moved ("kept") stops at the Files page with a card offering the saved
copy, because the Proposal step saves the copy it is opened on as it loads (review of fix 4). The
Proposal step only composes unattended when what it loaded is the server's copy or "ahead" of it,
asked before its own load save can land. A page that initDraftSync is reloading onto another
project writes nothing at all.

EXECUTED, NOT READ: js/files-door-harness.js runs the real shared.js (one vm per page load, one
browser, one stub server) with the real Proposal-step and Files-page code; see its header. The last
test hands the draft that harness produced to the REAL backend and reads the .docx it builds.
"""
import copy
import io
import json
import pathlib
import re
import shutil
import subprocess
import zipfile

import pytest
from fastapi.testclient import TestClient

import drafts
import main

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "files-door-harness.js"
client = TestClient(main.app)
NESTED = ["proposal_payload", "proposal_payload_key", "generate_result", "dropbox_result",
          "priced_tabs"]


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS)], capture_output=True, text=True,
                          encoding="utf-8", timeout=120)
    assert proc.returncode == 0, (
        "the harness itself failed — read this before assuming a product bug:\n" + proc.stderr)
    return json.loads(proc.stdout.strip().splitlines()[-1])


# ── the door ─────────────────────────────────────────────────────────────────────────────────
def test_a_document_that_is_current_is_left_alone(ran):
    """Arriving straight from Continue, and reloading the Files page after, with nothing changed:
    no trip through the Proposal step, and nothing written.

    Mutation: drop the key comparison from the door (always compose) — both arrivals navigate."""
    e = ran["e2e"]
    assert e["afterContinue"]["nav"] == [] and e["afterContinue"]["calls"] == ["showPostGenerate"]
    assert e["reload"]["nav"] == [], e["reload"]
    assert e["again"]["nav"] == [], "a Files reload after the door rebuilt it went round again"


def test_a_moved_draft_is_sent_through_the_proposal_step(ran):
    """THE DEFECT. The Estimate step re-priced ($10,000 → $12,500) and picked Orange Peel; a
    Proposal-step visit left the tax Broken out and a new note, with no Continue. The Files pill
    must not show the old document: it REPLACES itself with the Proposal step's door, shows
    nothing, and writes nothing.

    Mutations: return before the door (the old document is shown: showPostGenerate is called);
    `assign` instead of `replace` (Back from Files lands on a page that bounces forward)."""
    a = ran["e2e"]["arrive"]
    assert a["nav"] == [["replace", "/proposal-review.html?compose=files&d=d1"]], a["nav"]
    assert a["calls"] == [], "the stale document was put on screen before the door"
    assert ran["e2e"]["putsByArrival"] == 0


def test_the_door_builds_the_document_from_what_changed(ran):
    """What the Proposal step composes on the estimator's behalf carries every change, through the
    real pricing path: the new total, the Orange Peel texture, the Broken-out tax (base line, its
    own Material Sales Tax row, no parenthetical), and the new note.

    Mutation: make composeForFiles return before continueToDone — the payload keeps Smooth / $10,000."""
    c = ran["e2e"]["composed"]
    assert c["texture"] == "Orange Peel"
    assert c["total"] == "$12,500"
    assert c["taxInclusion"] == "BROKEN_OUT" and c["baseTaxPhrase"] == ""
    assert (c["baseBid"], c["materialTax"]) == ("$12,100", "$400")
    assert c["notes"] == ["New note line"]


def test_the_door_saves_to_the_server_before_it_opens_the_files_page(ran):
    """The Files page renders the SERVER's copy and has no pending save of its own to wait for,
    so the door's write must have landed before it navigates — and it navigates by REPLACING
    itself, marked `composed=1`.

    Mutations: drop `await TW.flushState()` from continueToDone (the PUT is missing before the
    replace); `assign` instead of `replace` on the door."""
    e = ran["e2e"]
    assert e["doorLog"] == ["PUT", "replace /done.html?composed=1&d=d1"], e["doorLog"]
    assert e["doorNote"] == ""


def test_what_the_files_page_downloads_is_the_rebuilt_document(ran):
    """Back on Files, marked: not sent round again, the mark taken off the address (so a reload
    comes back through the door), the key holds, and /documents renders the rebuilt payload.

    Mutation: leave the `composed` mark on the address — the url keeps `composed=1`."""
    e = ran["e2e"]
    assert e["back"]["nav"] == [] and e["back"]["composedHere"] is True
    assert e["back"]["url"] == "/done.html?d=d1"
    assert e["keyNow"] == e["keyStored"] and e["keyStored"]
    r = e["rendered"]
    assert (r["texture"], r["total"], r["taxInclusion"]) == ("Orange Peel", "$12,500", "BROKEN_OUT")


def test_the_documents_values_no_longer_nest_the_draft(ran):
    """`values` was a spread of the whole draft, so it carried the previous payload, the last
    build's result, the Dropbox result and the tab snapshot — one level deeper per Continue. The
    fixture's ancient payload nests two levels and a build; none of it may reach the new one.

    Mutation: drop the delete loop in continueToDone — every NESTED key comes back."""
    for name in ("firstPayload", "composed", "rendered"):
        s = ran["e2e"][name]
        assert s["nested"] == [], (name, s["nested"])
        assert s["mentionsAncient"] is False, name


def test_values_work_type_is_the_template_the_payload_names(ran):
    """A base flip to the Polish tab, left by Back: the door builds a POLISH document, and
    `values.work_type` agrees with the payload's own work_type (narrative defaults key on it)."""
    f = ran["flip"]
    assert f["arriveNav"] == [["replace", "/proposal-review.html?compose=files&d=d1"]]
    assert (f["payload"]["workType"], f["payload"]["valuesWorkType"]) == ("polish", "polish")
    assert f["payload"]["total"] == "$8,000"
    assert ran["e2e"]["composed"]["valuesWorkType"] == ran["e2e"]["composed"]["workType"]


def test_view_files_stays_view_files_through_the_door(ran):
    """View files off the board (`files=1`) goes through the door and comes back as View files,
    and the cover letter ticked since the last Continue rides the rebuilt document (it is page 1).
    This replaces the old check that the Files page's own rebuild carried the letter: that rebuild
    is gone (test_files_download_fresh.py).

    Mutation: drop the `&files=1` pass-through on either side — the page lands on the review
    card instead of the downloads."""
    v = ran["viewFiles"]
    assert v["arriveNav"] == [["replace", "/proposal-review.html?compose=files&files=1&d=d1"]]
    assert v["doorNav"] == [["replace", "/done.html?composed=1&files=1&d=d1"]]
    assert v["backCalls"] == ["viewFiles"] and v["backFilesMode"] is True
    assert v["texture"] == "Orange Peel"
    assert v["letter"] is True


def test_a_stale_copy_of_the_draft_is_not_written_back(ran):
    """THE SAFETY PROPERTY. Kyle's browser holds a copy that is current by its own key, while RJ
    has since revised the project and pressed Continue on another machine. View files must neither
    rebuild nor write: it puts the server's (RJ's) copy in place of Kyle's older one, reloads onto
    it, and renders RJ's document. Kyle's copy is gone from his browser too, so nothing on the page
    can put it back later.

    Mutation: decide on this browser's copy instead of the server's (skip reconcileWithServer) —
    the arrival shows Kyle's copy and his browser keeps it."""
    s = ran["staleLocal"]
    assert s["nav"] == [["reload"]] and s["calls"] == [], s
    assert s["againNav"] == [] and s["againCalls"] == ["viewFiles"], s
    assert s["putsFromThisBrowser"] == 0
    assert s["rendered"] == "RJ's texture" == s["serverTexture"] == s["localTexture"]


def test_view_files_never_builds_from_an_older_copy_over_a_colleagues_revision(ran):
    """Review findings 2 and 5. Kyle's key did not hold (an Estimate-step note saved after his last
    Continue), so the door did run — and it composed from Kyle's copy and PUT it: RJ's $15,000 and
    texture reverted, Troy's Won erased. Now it composes from the SERVER's copy: the one write is
    RJ's price, RJ's texture, Troy's Won and Kyle's own saved note, with a document built from them.

    Mutations: skip the adopt in reconcileWithServer (every put is Kyle's $10,000 Smooth, Won
    erased); drop the server check from composeForFiles (the same)."""
    s = ran["staleEdited"]
    assert s["finalCalls"] == ["viewFiles"], s["stops"]
    assert s["puts"] == 1 and s["everyPutIsRJs"] is True, s
    assert s["server"] == {"texture": "RJ Orange Peel", "lump": 15000,
                           "won": {"at": "2026-09-24", "by": "troy@wetreadwell.com"},
                           "handedOff": False}
    for name in ("document", "rendered"):
        assert (s[name]["texture"], s[name]["total"]) == ("RJ Orange Peel", "$15,000"), s[name]
        assert s[name]["notes"] == ["Kyle's later note"]


def test_a_copy_saved_before_this_deploy_is_not_written_back_either(ran):
    """The same, for a copy with no key and no record of when it last matched the server — every
    browser's copy on deploy day. The server's copy wins; Kyle's is never PUT.

    Mutation: treat a missing sync record as "this browser has unsaved changes" — the page keeps
    Kyle's copy, and the door stops instead of building."""
    s = ran["legacyStale"]
    assert s["settled"] is True and s["stops"] == ["done", "proposal", "done"], s
    assert s["puts"] == 1 and s["everyPutIsRJs"] is True
    assert s["serverTexture"] == "RJ Orange Peel" == s["documentTexture"]


def test_the_door_asks_the_servers_copy_not_this_browsers(ran):
    """Review finding 3. Kyle's copy holds by its own key; the SERVER's draft moved (RJ picked
    Knockdown on another machine, no Continue), so its document says Smooth. Download and Send
    render the server's copy, so the door has to ask that one: View files builds Knockdown.

    Mutation: ask this browser's key only (the old door) — no trip, and Download renders Smooth."""
    s = ran["serverMoved"]
    assert s["stops"] == ["done", "proposal", "done"], s
    assert s["documentTexture"] == "Knockdown" == s["renderedTexture"]
    assert s["keyHolds"] is True


def test_a_copy_with_edits_the_server_never_got_is_built_and_saved(ran):
    """This browser's copy has an edit whose save failed, and nobody has saved the server's copy
    since this browser last saw it ("ahead"). The Files page does not replace the edit — it may be
    the estimator's own work — and building from it and saving it loses nothing of anyone's, so the
    door does: the edit reaches the server and the document. (Before the review of fix 4 the door
    stopped here with a note, leaving the edit unsaved; with the "kept" case now stopping at the
    Files page, that note would have been a copy nobody could get out of.)

    Mutations: return "kept" for "ahead" in reconcileWithServer — the Files page stops and the
    edit never reaches the server; leave "ahead" out of the door's routing (the server's own key
    holds, so the Files page shows the old document); refuse the Proposal step an "ahead" copy
    (TW.bootSynced) — it goes back and forth."""
    s = ran["unconfirmed"]
    assert s["stops"] == ["done", "proposal", "done"], s
    assert s["puts"] == 1
    assert s["localTexture"] == "Unsaved Knockdown" == s["serverTexture"]


def test_an_edit_still_on_its_way_to_the_server_is_built_once_it_lands(ran):
    """A pill click sends the Estimate step's save as the page goes, so the Files page can ask the
    server before it has landed. It must not decide that the OLD document is current: it goes
    through the door, and the Proposal step, asking once more, finds the two copies agreeing.

    Mutation: decide "kept" on the server's key alone — the Files page shows the old document."""
    s = ran["inFlight"]
    assert s["firstNav"] == [["replace", "/proposal-review.html?compose=files&d=d1"]], s
    assert s["stops"] == ["proposal", "done"], s
    assert s["documentTexture"] == "Knockdown"


def test_a_page_reloading_onto_this_project_never_builds_from_another(ran):
    """Review finding 1. The door page is open on X when another tab opens Y. The door refuses
    ("open in another tab") and the estimator reloads as told: that load's snapshot is Y's, and
    initDraftSync adopts X and reloads. The door used to press Continue with Y's snapshot the moment
    TW.draftReady resolved — X saved with Y's name, scope and price. Nothing is written from that
    page now; the reload builds X from X.

    Mutations: drop `_reloadPending` from setState and the reloadPending check in composeForFiles
    together (Y reaches the server)."""
    s = ran["foreignReload"]
    assert "another tab" in s["said"]
    assert s["reload1Nav"] == [["reload"]] and s["putsAfterFirst"] == 0, s
    assert s["localAfterFirst"] == {"project": "Door Test", "texture": "Orange Peel", "lump": 10000}, (
        "the leftover page's own init wrote the other project's price into this one")
    assert s["reload2Nav"] == [["replace", "/done.html?composed=1&d=d1"]], s
    assert s["serverMentionsY"] is False and s["putsMentioningY"] == 0
    assert s["server"] == {"project": "Door Test", "scope": "Grind and coat.",
                           "docProject": "Door Test", "docTexture": "Orange Peel"}


def test_a_door_opened_while_this_browser_held_another_project_writes_nothing_of_it(ran):
    """The same from a plain load: a restored tab, a pasted link, Back to a door that had stopped.

    Mutation: as above."""
    s = ran["crossDraft"]
    assert s["firstNav"] == [["reload"]] and s["putsFromFirst"] == 0, s
    assert s["secondNav"] == [["replace", "/done.html?composed=1&d=d1"]]
    assert s["serverMentionsY"] is False and s["putsMentioningY"] == 0
    assert s["docTexture"] == "Orange Peel"


def test_a_copy_edited_after_a_fresh_hydrate_is_known_to_hold_unsaved_changes(ran):
    """The record of what the server held is taken at the hydrate as well as at every stored save:
    otherwise a copy read fresh from the server and then edited, with a save that failed, looks
    like one that never changed, and the Files page puts the server's copy over the edit. With the
    record, the Files page knows the server has not moved since, so the edit is built and saved.

    Mutation: record nothing at the hydrate (shared.js adoptAndReload) — the edit is replaced."""
    s = ran["hydratedThenUnsaved"]
    assert s["hydrateNav"] == [["reload"]], s
    assert s["stops"] == ["done", "proposal", "done"], s
    assert s["puts"] == 1
    assert s["localTexture"] == "Unsaved Knockdown" == s["serverTexture"], s


def test_the_cover_letter_ticked_on_this_visit_survives_the_next_rebuild(ran):
    """Review finding 6. The switch writes a top-level primitive with setState; the page's snapshot
    still said false, and Continue spread that snapshot back over the tick. The payload said true,
    so the key held and nobody saw it — until the next build (the door, after a note changed on
    the Estimate step) read the unticked box and dropped page 1 from the customer's document.

    Mutation: build mergedValues from the snapshot alone — afterTick.topLevel is False and the
    door's document has no letter."""
    s = ran["coverLetter"]
    assert s["afterTick"] == {"topLevel": True, "payload": True}, s
    assert s["afterDoor"]["topLevel"] is True and s["afterDoor"]["payload"] is True, s
    assert s["afterDoor"]["notes"] == ["A later note"]


def test_an_older_document_put_back_goes_through_the_door_too(ran):
    """The key covers the DOCUMENT as well as the inputs: a write that restored an older
    `proposal_payload` and nothing else (a late debounced save) is not mistaken for current.

    Mutation: key only the inputs in TW.composeKey — this arrival shows the old document."""
    d = ran["documentOnly"]
    assert d["nav"] == [["replace", "/proposal-review.html?compose=files&d=d1"]], d
    assert d["calls"] == []


def test_a_page_just_built_is_never_sent_round_again(ran):
    """The loop guard. Marked `composed=1`, the page stays even when its key does not hold (the
    Send button checks the key again); the same draft arriving unmarked goes through the door.

    Mutation: drop `!composedHere` from the door — the marked arrival navigates too."""
    g = ran["loopGuard"]
    assert g["marked"] == [], g
    assert g["unmarked"] == [["replace", "/proposal-review.html?compose=files&d=d1"]], g


def test_no_project_means_the_empty_page_not_the_proposal_step(ran):
    """Nothing in flight: the Proposal step would only say "No project started", so the Files
    page shows its own empty state and sends nobody anywhere.

    Mutation: drop `st.project_name &&` from the door — it sends the empty draft to compose."""
    n = ran["noProject"]
    assert n["nav"] == [] and n["calls"] == [] and n["emptyShown"] is True, n


def test_the_door_never_builds_unattended_without_the_template(ran):
    """With no template on screen the editor's edits cannot be read and the version is "" (which
    the backend reads as "apply every edit"), so the door stops and says why; the same when the
    page never settles. Nothing navigates, nothing is written, Continue is handed back.

    Mutations: drop the `!templateVersion` test (the no-template page navigates); drop the timeout
    (the page that never settles waits forever and this scenario hangs)."""
    u = ran["unattended"]
    for case in ("noTemplate", "neverSettles"):
        assert u[case]["nav"] == [], case
        assert "could not be done for you" in u[case]["note"], u[case]["note"]
    assert u["noTemplate"]["shown"] is True and u["noTemplate"]["disabled"] is False
    assert u["noTemplate"]["button"].startswith("Continue to Done")
    assert u["putsFromEither"] == 0


def test_a_save_the_door_cannot_make_goes_nowhere(ran):
    """Another tab took this browser's copy, or the server is down: the Files page must not open
    on the old document. Each says why, in the page's own words.

    Mutation: navigate when flushState fails — the server-down page opens Files."""
    r = ran["refusedSave"]
    assert r["foreign"]["nav"] == [] and "another tab" in r["foreign"]["note"]
    assert r["serverDown"]["nav"] == []
    assert "could not be saved" in r["serverDown"]["note"]
    assert r["serverDown"]["button"].startswith("Continue to Done")


def test_a_pending_form_save_cannot_put_the_old_document_back(ran):
    """The form's 300ms persist writes a patch of the page snapshot's OLD payload. One still
    pending when Continue runs is cancelled, so the new document and its key stand.

    Mutation: drop the clearTimeout in continueToDone — the old texture comes back and the key
    no longer holds."""
    p = ran["latePersist"]
    assert p["texture"] == "Orange Peel" and p["serverTexture"] == "Orange Peel"
    assert p["keyHolds"] is True


def test_the_estimate_steps_pills_save_the_sheet_on_the_way_out(ran):
    """A cell edit reaches the draft only when the grid's `change` handler runs persistTabState
    300ms later; clicking a pill fires `change` and navigates at once. A pill clicked while that
    save is waiting runs it now (once — the timer is cancelled); a click anywhere else does not.

    Mutation: drop the listener — the edited page's afterPill is 0."""
    p = ran["estimatePill"]
    assert p["events"] == ["click", "grid:change"]
    assert p["armed"] is True and p["afterPill"] == 1 and p["clearedByPill"] is True
    assert p["afterDebounce"] == 1, "the cancelled debounce still fired a second save"
    assert p["elsewhere"] == 0


def test_a_pill_click_with_no_edit_waiting_writes_nothing(ran):
    """Review finding 5, its second path. persistTabState writes the page's whole load-time
    snapshot, so a pill click on an Estimate page opened before a colleague's revision put that old
    copy back over theirs — merely walking through the step. With no edit waiting it writes nothing,
    as before the listener existed; once the debounce has saved an edit itself, there is nothing
    left waiting either.

    Mutations: persist on every pill click (idle is 1); leave `_cbTimer` set when the debounce
    fires (settledAfterPill is 2)."""
    p = ran["estimatePill"]
    assert p["idle"] == 0
    assert p["settledSaves"] == 1 and p["settledAfterPill"] == 1
    assert p["settledPending"] is None


# ── the review of fix 4 (2026-09-25) ─────────────────────────────────────────────────────────
RJ_STANDS = {"texture": "RJ Orange Peel", "lump": 15000, "won": True,
             "notes": "Kyle's note, sent as the tab closed", "docTotal": "$15,480.00"}


def test_a_copy_where_both_sides_moved_stops_at_the_files_page(ran):
    """Finding 1. Kyle's note reached the server as his tab closed, with nobody left to record that
    it had; RJ then re-priced to $15,000 and pressed Continue on his machine, and Troy marked the job
    Won. The Files page found Kyle's copy "kept" and sent it through the door, and the Proposal
    step's load save put his $10,000 copy back over RJ's price, texture and the Won. Now the Files
    page stops: no door, no PUT (even once the page's timers have run), and a card that says why
    with one button, Load the saved copy.

    Mutations: send a "kept" copy through the door (the page leaves for the Proposal step); decide
    "adopted" for a copy both sides moved (Kyle's copy is dropped without asking)."""
    s = ran["bothMoved"]
    assert s["nav"] == [] and s["calls"] == [] and s["emptyShown"] is True, s
    assert s["card"]["title"] == "This project was changed somewhere else", s["card"]
    assert s["card"]["button"] == "Load the saved copy"
    assert "Nothing was rebuilt or saved" in s["card"]["lede"]
    assert s["putsByArrival"] == 0
    assert s["keptKyles"] == {"texture": "Smooth", "notes": "Kyle's note, sent as the tab closed"}


def test_loading_the_saved_copy_puts_the_colleagues_work_in_this_browser(ran):
    """The card's button replaces this browser's copy with the server's and reloads. The reload finds
    a current document (RJ's), shows the files, and writes nothing: RJ's $15,000 and the Won stand.

    Mutation: have useServerCopy leave this browser's copy in place (it is still Kyle's)."""
    s = ran["bothMoved"]
    assert s["pressNav"] == [["reload"]], s
    assert s["localAfterPress"] == {"texture": "RJ Orange Peel", "lump": 15000, "won": True}
    assert s["afterReload"]["stops"] == ["done []"] and s["afterReload"]["calls"] == ["viewFiles"], s
    assert s["putsFromKyle"] == 0
    assert s["server"] == RJ_STANDS


def test_loading_the_saved_copy_never_drops_another_tabs_project(ran):
    """The card was up when another tab of this browser opened project Y, so the local copy is Y's.
    Pressing Load the saved copy saves Y's copy under Y's own id before X's takes its place, the way
    opening a project does.

    Mutation: write the server's copy over the local one without saving Y's first (no PUT to Y)."""
    s = ran["pressWhileAnotherTabHeldY"]
    assert s["pressNav"] == [["reload"]], s
    assert s["yPuts"] == ["Other Project Y"], s
    assert s["local"] == {"project": "Door Test", "texture": "RJ Orange Peel", "stamp": "d1"}, s


def test_a_press_that_cannot_read_the_saved_copy_says_so(ran):
    """The server cannot be read at the press: this browser's copy stays, nothing reloads, and the
    card says what happened, so the button is never one that silently does nothing.

    Mutation: drop the card's failure line — the lede is still the first one."""
    s = ran["pressWhileServerDown"]
    assert s["nav"] == [], s
    assert s["texture"] == "Smooth", s
    assert s["lede"].startswith("The saved copy could not be read"), s


def test_the_door_on_a_copy_that_is_not_the_servers_goes_back_and_saves_nothing(ran):
    """Finding 1, the Proposal step's half. Opened as the door on such a copy all the same, the page
    asks the server AT ONCE — before its own load save (2.5 s) could land and make the two copies
    look equal, which is how the old check waved a stale build through — holds that save unsent
    (TW.holdServerSaves), and goes back to the Files page. Quick template or slow, nothing reaches
    the server.

    Mutations: ask only after this page's own save has gone and accept "the server equals this
    page now", as before (a PUT of Kyle's copy, then a build from it); build anyway (a PUT); hold
    nothing in composeForFiles (one PUT of Kyle's copy)."""
    s = ran["doorOnBothMoved"]
    for case in ("quickTemplate", "slowTemplate"):
        assert s[case]["nav"] == [["replace", "/done.html?d=d1"]], (case, s[case])
        assert s[case]["puts"] == 0, (case, s[case])
        assert s[case]["server"] == RJ_STANDS, (case, s[case])


def test_a_server_that_cannot_be_read_is_not_answered_by_the_door(ran):
    """The server cannot be read at the Files page and the document is out of date. The Proposal
    step saves as it loads, so it is not sent a copy nobody could check: the card says so, and its
    button reloads.

    Mutation: send an "unreachable" copy through the door."""
    s = ran["unreachable"]
    assert s["nav"] == [] and s["calls"] == [], s
    assert s["card"]["title"] == "Couldn't check the saved project", s["card"]
    assert s["puts"] == 0
    assert s["pressNav"] == [["reload"]]


def test_the_letters_new_wording_survives_continue_and_the_next_rebuild(ran):
    """Finding 3. coverletter-editor.js (loaded whole) keeps the letter's wording in four top-level
    keys it REPLACES with setState. Continue spread the page's load-time snapshot of them back over
    the new wording: the payload said X1, the draft X0, and the door's unattended rebuild then put
    X0 into the customer's letter. Now both say X1 after Continue, and so does the rebuild.

    Mutation: drop the live read of the four keys in continueToDone — topLevel and the door's
    payload read the first wording."""
    s = ran["letterWording"]
    x1 = {"3": {"text": "Dear Sam — the wording Kyle settled on."}}
    a = s["afterContinue"]
    assert a["payload"] == a["topLevel"] == a["store"] == x1, a
    assert a["keyHolds"] is True
    assert s["stops"] == ["done", "proposal", "done"], s
    assert s["afterDoor"]["payload"] == s["afterDoor"]["topLevel"] == x1, s["afterDoor"]
    assert s["afterDoor"]["notes"] == ["A later note"]


def test_the_boards_marks_do_not_rebuild_the_proposal(ran):
    """Finding 5. Who is told about a send, Lost, On hold, Won and Handed off are written into the
    draft by the server from the CRM, and no template prints them. As proposal inputs, each one
    made the next View files rebuild the proposal on whichever machine opened it. Troy's machine
    now takes the server's copy (with the Won) and shows the files: no rebuild, no save, and the
    letter still carries Kyle's address.

    Mutation: take the board's marks off COMPOSE_IGNORED — Troy's View files rebuilds (a PUT)."""
    s = ran["boardMarks"]
    assert s["stops"] == ['done [["reload"]]', "done []"], s
    assert s["finalCalls"] == ["viewFiles"]
    assert s["puts"] == 0
    assert s["won"] is True
    assert s["email"] == "kyle@wetreadwell.com"


def test_a_rebuild_on_a_colleagues_machine_is_still_signed_by_the_estimator(ran):
    """Finding 5. computeTokenValues signed with whoever was signed in, so the door rebuilding
    Kyle's project on Troy's machine printed "Kyle Loseke | Estimator troy@wetreadwell.com" on the
    customer's letter. The saved document's address now stays while the same name signs.

    Mutation: sign with the viewer's address always (the old line) — troy@ on Kyle's letter."""
    s = ran["signing"]["rebuiltByTroy"]
    assert s["puts"] == 1 and s["texture"] == "Orange Peel", s
    assert (s["name"], s["email"]) == ("Kyle Loseke", "kyle@wetreadwell.com"), s


def test_a_document_saved_without_an_address_gets_only_its_own_signers(ran):
    """A document composed before the letter carried an address (2026-09-09) is signed Kyle with
    none. Rebuilt on Troy's machine it still prints none — never Troy's; rebuilt by Kyle, his own.

    Mutation: fall back to the viewer's address whenever the saved one is blank — troy@ on Kyle's."""
    r = ran["signing"]
    assert (r["legacyByTroy"]["name"], r["legacyByTroy"]["email"]) == ("Kyle Loseke", ""), r
    assert (r["legacyByKyle"]["name"], r["legacyByKyle"]["email"]) == (
        "Kyle Loseke", "kyle@wetreadwell.com"), r


def test_a_blank_signature_field_takes_the_saved_documents_signer(ran):
    """The project's own signature field was never filled in; its saved document says Kyle.
    prefillEstimator (the page's own init, run by the harness) filled the field with the viewer,
    so Troy's machine signed the whole proposal as Troy.

    Mutation: drop the saved document's name from prefillEstimator — name and address are Troy's."""
    s = ran["signing"]["blankFieldByTroy"]
    assert (s["name"], s["email"]) == ("Kyle Loseke", "kyle@wetreadwell.com"), s


def test_a_new_name_on_the_signature_line_signs_with_its_typists_address(ran):
    """The counterexample: Troy types his own name on the line and presses Continue. That is a new
    signer, so the document is his, at his address — the saved document's address does not follow
    a name it no longer belongs to.

    Mutation: keep the saved address whatever the name — kyle@ under Troy Holmes."""
    s = ran["signing"]["troySigns"]
    assert (s["name"], s["email"]) == ("Troy Holmes", "troy@wetreadwell.com"), s


# ── the review of fix 4, round 2 (2026-09-25) ────────────────────────────────────────────────
RJ_REVISION = {"texture": "RJ Orange Peel", "lump": 15000, "won": True,
               "assigned": "rj@wetreadwell.com", "docTotal": "$15,480.00"}


def test_opening_another_project_never_puts_an_in_sync_copy_back(ran):
    """Finding 1 (on prod before this branch). Kyle's browser still held project X, in sync when he
    last had it open. RJ then re-priced X to $15,000 and Troy marked it Won and gave it to RJ.
    Kyle opened another project, and initDraftSync's eviction PUT his copy of X to X, putting his
    $10,000 back over all of it. A copy that is still the one this browser last saw the server
    store holds nothing to save: nothing is sent.

    Mutation: drop the synced-record check in flushEvictedBlob — one PUT to X of "Smooth"."""
    s = ran["evict"]["inSync"]
    assert s["nav"] == [["reload"]], s
    assert s["putsToX"] == [], s
    assert s["server"] == RJ_REVISION, s


def test_an_evicted_copy_with_a_change_the_server_never_got_is_still_saved(ran):
    """The counterexample, and the reason the eviction exists: a change whose save never landed
    (a large draft's pagehide keepalive fails outright) is saved under its own id before the copy
    is replaced. So is a copy with no record at all, written before the record existed — the
    trade-off stays where it was for those, and this pins it.

    Mutation: never flush an evicted copy — both lose their PUT."""
    e = ran["evict"]
    assert e["unsavedEdit"]["putsToX"] == ["Kyle's edit that never reached the server"], e
    assert e["noRecord"]["putsToX"] == ["Smooth"], e


def test_to_dropbox_on_an_open_files_page_writes_nothing_over_a_revision(ran):
    """Findings 2A and 7. Kyle's Files page for X was current and left open; RJ revised X on his
    machine; Kyle pressed To Dropbox. The server filed RJ's document (and recorded the filing on
    its own copy), then the page's TW.setState PUT Kyle's whole copy back, so the draft said
    $10,000 while Dropbox held $15,480, and the next Send froze the $10,000 one. The real button
    handler, lifted out of dropbox.js, now records the filing in this browser only.

    Mutation: TW.setLocalState -> TW.setState in dropbox.js — one PUT of "Smooth"."""
    s = ran["dropboxPress"]
    assert s["arrival"] == ["showPostGenerate"], s
    assert s["filed"] == ["RJ Orange Peel"], s
    assert s["putsFromPress"] == [], s
    assert s["server"] == RJ_REVISION, s
    assert s["keptHere"] == "/Estimating/*Kyle/Door Test", "the green 'already filed' state is gone"


def test_the_estimator_picker_rereading_the_assignment_writes_nothing(ran):
    """Finding 2B. Every showPostGenerate re-reads the assignment (mountEstimatorPicker ->
    TW.refreshServerOwned). Troy had given X to RJ, so it had "moved", and its setState PUT Kyle's
    whole copy over RJ's revision. The picker still reads RJ; nothing is sent.

    Mutation: setLocalState -> setState in refreshServerOwned — one PUT of "Smooth"."""
    s = ran["pickerRefresh"]
    assert s["patch"] == {"assigned_estimator": "rj@wetreadwell.com"}, s
    assert s["pickerReads"] == "rj@wetreadwell.com"
    assert s["puts"] == [], s
    assert s["server"] == RJ_REVISION, s


def test_a_server_that_cannot_be_read_stops_the_files_page_even_on_a_keyed_copy(ran):
    """Finding 2C. With the server unreadable as the page opened and this browser's own copy
    keyed, the page carried on from a copy nobody had checked. It now stops on the same card as
    any other copy the server could not be asked about, writes nothing, and its button reloads.

    Mutation: restore `!holds` on the "unreachable" stop — the page carries on to viewFiles."""
    s = ran["unreachableKeyed"]
    assert s["keyedHere"] is True, "the scenario lost its point: this copy is not keyed"
    assert s["nav"] == [] and s["calls"] == [], s
    assert s["card"]["title"] == "Couldn't check the saved project", s["card"]
    assert s["puts"] == []
    assert s["pressNav"] == [["reload"]]


def test_the_door_asks_again_as_it_saves(ran):
    """Finding 5. The door's first question was a yes (the server held the page's copy), and a yes
    as the page opened said nothing about the 20 s after it: RJ's Continue landing while the
    template loaded was put back to Kyle's copy by the page's 2.5 s load save or by Continue, and
    the next Send froze Kyle's document. Every save the door page makes is now asked the same
    question again as it is sent: either way round, nothing is PUT and the page goes back to the
    Files page, with RJ's revision standing. With nobody landing, it builds and saves once.

    Mutations: let scheduleServerSave queue a save while held (the load save lands); drop the gate
    from flushState (Continue lands)."""
    w = ran["doorWindow"]
    for when in ("beforeLoadSave", "afterLoadSave"):
        s = w[when]
        assert s["nav"] == [["replace", "/done.html?d=d1"]], (when, s)
        assert s["puts"] == [], (when, s)
        assert (s["serverTexture"], s["docTexture"], s["docTotal"]) == (
            "RJ Orange Peel", "RJ Orange Peel", "$15,480.00"), (when, s)
    q = w["nobody"]
    assert q["nav"] == [["replace", "/done.html?composed=1&d=d1"]], q
    assert q["puts"] == ["Kyle Orange Peel"], q
    assert q["docTexture"] == "Kyle Orange Peel", q


def test_the_cover_letters_own_save_cannot_leave_a_door_that_found_another_copy(ran):
    """Finding 6. The door page's one-off cancel of its queued save ran when the server read
    answered. The REAL cover-letter editor queues a save of its own when its template arrives
    (persistNow), and when that came after the read, the page's pagehide sent Kyle's whole copy
    over RJ's revision and Troy's Won. Whichever answers first, the letter's save is made in this
    browser (it did write) and nothing reaches the server, the page closing included.

    Mutation: let scheduleServerSave queue a save while held — letterAfterTheRead makes one PUT."""
    r = ran["letterAfterVerdict"]
    for order in ("letterFirst", "letterAfterTheRead"):
        s = r[order]
        assert s["letterAsked"] is True and s["letterSavedHere"] is True, (order, s)
        assert s["nav"] == [["replace", "/done.html?d=d1"]], (order, s)
        assert s["puts"] == [], (order, s)
        assert s["server"] == RJ_STANDS, (order, s)


# ── the backend builds that document ─────────────────────────────────────────────────────────
@pytest.fixture
def served(ran, monkeypatch, fake_supabase):
    blob = copy.deepcopy(ran["e2e"]["serverBlob"])
    blob.pop("__draft_id", None)
    store = {"drafts": [{"id": "d1", "owner_email": "kyle@wetreadwell.com", "data": blob}]}
    monkeypatch.setattr(drafts, "get_client", lambda: fake_supabase(store))
    monkeypatch.setattr(drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": "admin"})
    return blob


def _docx_text(content):
    xml = zipfile.ZipFile(io.BytesIO(content)).read("word/document.xml").decode("utf-8")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", xml))


def test_the_server_builds_the_changed_proposal_and_the_send_gate_agrees(served):
    """The draft the door saved, through the REAL /api/draft/{id}/documents and the real
    templates: the .docx carries the new total, texture, tax rows and note, and none of the old
    ones — and the publish gate (_stale_document_refusal) has nothing to refuse, because the page
    half and the document half of the draft were composed together."""
    r = client.post("/api/draft/d1/documents", json={})
    assert r.status_code == 200, r.text
    f = client.get(r.json()["docx_download_url"])
    assert f.status_code == 200, f.text
    text = _docx_text(f.content)
    for want in ("$12,500", "$12,100", "$400", "Material Sales Tax", "Orange Peel",
                 "New note line"):
        assert want in text, (want, text[:2000])
    for old in ("$10,000", "Smooth", "Old note"):
        assert old not in text, (old, text[:2000])
    # Hanz, on this layout: "If remodel tax is off then in the broken out option in the Proposal,
    # there is no remodel tax but there is material sales tax." Remodel is $0 on this draft.
    assert "Remodel Tax" not in text, text[:2000]
    assert main._stale_document_refusal(main._publish_digest(served)) is None


def _render_served(blob, work_type, audience, remodel_amount=None):
    """The door's saved draft, re-pointed at another template (and optionally given a remodel
    tax), through the REAL /api/draft/{id}/documents: the .docx text a customer would read."""
    pp = blob["proposal_payload"]
    pp["work_type"] = work_type
    pp["audience"] = audience
    pp["values"]["work_type"] = work_type
    pp["values"]["audience"] = audience
    blob["audience"] = audience
    if remodel_amount:
        pp["remodel"] = [{"amount_formatted": remodel_amount}]
        pp["values"]["tax_amount_formatted"] = remodel_amount
    r = client.post("/api/draft/d1/documents", json={})
    assert r.status_code == 200, r.text
    f = client.get(r.json()["docx_download_url"])
    assert f.status_code == 200, f.text
    return _docx_text(f.content)


# Every template family: the three GC files and the Gyp file author their Remodel Tax row as a
# plain paragraph (they printed "$0 – Remodel Tax" / "$0 – Kansas Remodel Tax"); the Direct files
# wrap it in {{#remodel}}.
REMODEL_TEMPLATES = [("epoxy", "GC"), ("polish", "GC"), ("sealer", "GC"), ("gyp", "Direct"),
                     ("epoxy", "Direct"), ("polish", "Direct"), ("combo", "Direct")]


@pytest.mark.parametrize("work_type,audience", REMODEL_TEMPLATES)
def test_remodel_off_broken_out_prints_material_tax_and_no_remodel_row(served, work_type, audience):
    """Hanz: "If remodel tax is off then in the broken out option in the Proposal, there is no
    remodel tax but there is material sales tax." The draft the door built is Broken out with no
    remodel tax; rendered through every template family, no Remodel Tax row prints and the Material
    Sales Tax row does.

    Mutation: pass `remodel_row=True` whatever the tax (main.py) — GC and Gyp print "$0 – Remodel
    Tax" again."""
    assert served["proposal_payload"]["values"]["tax_inclusion"] == "BROKEN_OUT"
    assert served["proposal_payload"]["remodel"] == []
    text = _render_served(served, work_type, audience)
    assert "Remodel Tax" not in text, (work_type, audience, text[:3000])
    assert "Material Sales Tax" in text, (work_type, audience, text[:3000])


@pytest.mark.parametrize("work_type,audience", [("epoxy", "GC"), ("gyp", "Direct")])
def test_a_payload_with_a_remodel_figure_but_no_remodel_list_keeps_its_row(served, work_type,
                                                                           audience):
    """Off is "no remodel line AND a remodel figure of nothing". A payload saved before the
    `remodel` list existed, with a real figure, still prints the row it always printed.

    Mutation: decide off on the list alone (main.py `_remodel_off`) — the row disappears."""
    served["proposal_payload"]["values"]["tax_amount_formatted"] = "$650"
    text = _render_served(served, work_type, audience)
    assert re.search(r"\$650 – (Kansas )?Remodel Tax", text), (work_type, audience, text[:3000])


@pytest.mark.parametrize("work_type,audience", [("epoxy", "GC"), ("gyp", "Direct"),
                                                ("epoxy", "Direct")])
def test_remodel_on_still_prints_its_row(served, work_type, audience):
    """The counterexample: with a remodel tax the row is still there, with its figure, beside the
    Material Sales Tax. Without this the test above passes for a writer that deletes every remodel
    row.

    Mutation: take the free rows out unconditionally (proposal_writer) — GC and Gyp lose the row."""
    text = _render_served(served, work_type, audience, remodel_amount="$650")
    assert re.search(r"\$650 – (Kansas )?Remodel Tax", text), (work_type, audience, text[:3000])
    assert "Material Sales Tax" in text
