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
it writes, the Files page recomputes the key on arrival, and a draft whose document is not current
is sent through the Proposal step with `?compose=files`, which presses Continue for it once the page
has settled and comes straight back. A document that IS current is left alone and nothing is
written, so opening a project's files on a machine holding an older copy of the draft cannot put
that copy back over a colleague's revision.

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
    has since revised the project on another machine. View files must neither rebuild from Kyle's
    copy nor write it: it renders the server's (RJ's) document and PUTs nothing.

    Mutation: always compose on arrival — the door runs and PUTs Kyle's copy over RJ's."""
    s = ran["staleLocal"]
    assert s["nav"] == [] and s["calls"] == ["viewFiles"]
    assert s["putsFromThisBrowser"] == 0
    assert s["rendered"] == "RJ's texture" == s["serverTexture"]


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
    300ms later; clicking a pill fires `change` and navigates at once. The pills now save the
    sheet first, as Back and Continue do; a click anywhere else does not.

    Mutation: drop the listener — nothing is persisted."""
    p = ran["estimatePill"]
    assert p["events"] == ["click"]
    assert p["afterPill"] == 1 and p["afterCell"] == 1


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
