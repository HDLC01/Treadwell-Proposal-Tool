"""The safety properties of step-5 filing, one test per defect found in review.

Two adversarial reviews of the existing-folder filing path (2026-08-20) found five
ways it could still hurt somebody. Each one is pinned here, and each test was
proved by reverting the fix and watching it fail — the reversal is named in the
docstring so the next person can repeat it.

  1. the "never clobber a human's file" probe read ANY error as "the path is free"
  2. the destination CATEGORY folder was an accepted filing target
  3. a picked folder was never checked against the destination in the same request
  4. the event-log write sat outside the try, so a store hiccup reported a
     successful filing as a failure — and the retry filed a second time
  5. the client's "nothing is filed until a folder is chosen" guard had an
     escape hatch for the already-uploaded state

The Dropbox doubles come from test_dropbox_route_contract.py: what matters in a
folder somebody else built is WHICH API calls we make in it, so the recording
client is the instrument for all of this. The exceptions, by contrast, are the REAL
SDK types — the whole point of defect 1 is how a genuine not-found differs from
every other failure, and a hand-rolled stand-in for that distinction would prove
nothing about the code that ships.
"""
import json
import pathlib
import shutil
import subprocess

import dropbox
import dropbox_client as dc
import main
import pytest
from dropbox.exceptions import (ApiError, AuthError, InternalServerError,
                                RateLimitError)
from dropbox.files import FolderMetadata, GetMetadataError
from dropbox.files import LookupError as DbxLookupError
from fastapi.testclient import TestClient
from test_dropbox_route_contract import RecordingDbx

ROOT = dc.ESTIMATING_ROOT
GYP = ROOT + "/$Gyp Estimates"
COMMERCIAL = ROOT + "/$Commercial Sales Estimates"
KYLES_FOLDER = GYP + "/26.08.14 Fuel House"
KYLES_NUMBERS = KYLES_FOLDER + "/Numbers 8.10.26"
OUR_XLSX = KYLES_NUMBERS + "/$ estimate sheet - Fuel House.xlsx"


def _not_found():
    """What Dropbox raises for a path that genuinely isn't there: an ApiError
    whose error union is path → not_found."""
    return ApiError("req-1", GetMetadataError.path(DbxLookupError.not_found), None, None)


def _not_a_folder():
    """A path error that is NOT not_found. Same union, different tag — this is the
    case a `str(exc)` check would get wrong in the dangerous direction."""
    return ApiError("req-2", GetMetadataError.path(DbxLookupError.not_folder), None, None)


class ProbeFailsDbx(RecordingDbx):
    """The recording client, except the occupancy probe for a FILE path raises
    `probe_error` instead of answering. The folder verification still works, so a
    test can put the failure exactly where _upload_beside asks its question."""

    def __init__(self, probe_error, **kw):
        super().__init__(**kw)
        self.probe_error = probe_error

    def files_get_metadata(self, path):
        if path in self.tree:                       # the project folder itself
            return super().files_get_metadata(path)
        self.calls.append(("get_metadata", path))
        raise self.probe_error


def _kyles_folder_tree(files=()):
    return dict(tree={KYLES_FOLDER: ["Numbers 8.10.26"], KYLES_NUMBERS: []},
                files=set(files))


def _file_into(dbx, **kw):
    """_file_into_existing_folder with the REAL dropbox module and the REAL
    ApiError, so the typed not-found check is the one under test."""
    kw.setdefault("folder_path", KYLES_FOLDER)
    kw.setdefault("project_name", "Fuel House")
    kw.setdefault("xlsx_bytes", b"xlsx")
    kw.setdefault("docx_bytes", b"docx")
    kw.setdefault("pdf_bytes", None)
    kw.setdefault("deadline", "2026-08-14")
    kw.setdefault("bid_date", None)
    kw.setdefault("work_type", "gyp")
    return dc._file_into_existing_folder(dbx, dropbox, ApiError, FolderMetadata, **kw)


def _uploads_of(dbx, suffix):
    return [c for c in dbx.calls if c[0] == "upload" and c[1].endswith(suffix)]


# ═══ 1. the occupancy probe ═══════════════════════════════════════════════════
# REVERSAL: in dropbox_client._upload_beside, put back
#     except Exception: occupied = False
@pytest.mark.parametrize("exc", [
    RateLimitError("req", None, 30),               # too_many_requests
    InternalServerError("req", 503, "oops"),       # Dropbox having a bad minute
    AuthError("req", None),                        # the token expired mid-send
    _not_a_folder(),                               # an ApiError that is NOT not_found
    RuntimeError("connection reset by peer"),      # the transport, not the API
])
def test_a_probe_that_fails_for_any_other_reason_counts_as_occupied(exc):
    """A failed probe means we DON'T KNOW whether Kyle's file is at that name, and
    "don't know" may not resolve to overwrite. An extra "… (1).xlsx" is recoverable
    by deleting it; an overwritten estimate sheet is gone.

    The mode is asserted rather than the folder contents: an overwrite is invisible
    afterwards, which is exactly why this went unnoticed."""
    dbx = ProbeFailsDbx(exc, **_kyles_folder_tree())
    res = _file_into(dbx)
    assert res["configured"] is True
    est = _uploads_of(dbx, ".xlsx")
    assert est, "nothing was uploaded at all"
    assert est[0][2].is_add() and est[0][3] is True, (
        "an unreadable probe was treated as a free name and overwrote blindly")
    docx = _uploads_of(dbx, ".docx")
    assert docx[0][2].is_add() and docx[0][3] is True


def test_a_genuine_not_found_is_still_a_free_name():
    """The other direction, and it costs real money if it breaks: treating every
    probe failure as occupied would autorename on EVERY send, so each re-file would
    drop another "$ estimate sheet - X (1).xlsx" into Kyle's folder. A typed
    path/not_found is the one answer that means free."""
    dbx = ProbeFailsDbx(_not_found(), **_kyles_folder_tree())
    res = _file_into(dbx, pdf_bytes=b"pdf")
    for suffix in (".xlsx", ".docx", ".pdf"):
        call = _uploads_of(dbx, suffix)[0]
        assert call[2].is_overwrite() and call[3] is False, suffix + " was autorenamed"
    assert res["renamed"] == []
    assert len(res["written_paths"]) == 3


def test_our_own_recorded_file_is_not_probed_at_all():
    """known_paths short-circuits the probe, so a Dropbox wobble can't turn a
    routine re-file of OUR OWN sheet into a second copy."""
    dbx = ProbeFailsDbx(RateLimitError("req", None, 30),
                        **_kyles_folder_tree(files=[OUR_XLSX]))
    res = _file_into(dbx, known_paths=(OUR_XLSX,))
    assert res["written_paths"][0] == OUR_XLSX and res["renamed"] == []
    assert ("get_metadata", OUR_XLSX) not in dbx.calls
    assert _uploads_of(dbx, ".xlsx")[0][2].is_overwrite()


def test_only_an_explicit_not_found_text_frees_a_non_sdk_error():
    """A deliberate, documented compromise, pinned so nobody removes it by
    accident. An exception that is not an SDK ApiError carries no error union to
    read, so the text is all there is — and it counts ONLY when it says not_found
    outright. Two other suites' fake clients raise exactly that
    (`RuntimeError("not_found: <path>")`) for a missing path, and their
    "a free name is a plain overwrite" assertions depend on this branch."""
    assert dc._is_path_not_found(RuntimeError("not_found: /x/y"), ApiError) is True
    assert dc._is_path_not_found(RuntimeError("429 too_many_requests"), ApiError) is False
    assert dc._is_path_not_found(_not_found(), ApiError) is True
    assert dc._is_path_not_found(_not_a_folder(), ApiError) is False


# ═══ 2. a category folder is not a filing target ══════════════════════════════
# REVERSAL: in dropbox_client._file_into_existing_folder, drop the `segments`
# check and keep only `not path or ".." in path or not path.startswith(root)`.
@pytest.mark.parametrize("bad", [
    GYP,                        # 80 real project folders live in here
    COMMERCIAL,                 # the category everyone shares
    GYP + "/$Archive",          # a "$" bucket one level down — also not one job
])
# The Estimating ROOT itself is deliberately NOT in that list: the older
# startswith() check already refuses it, so a case for it here would pass with the
# category rule reverted and prove nothing. It is covered in
# test_dropbox_route_contract.py instead.
def test_a_category_folder_is_refused_before_a_byte_moves(bad):
    """The picker only ever offers a category's CHILDREN, so a path this shallow is
    a stale tab or a hand-rolled request. Filing there drops a customer's estimate
    loose in a folder the whole team shares — and the additive rules would keep it
    there quietly, since nothing gets created or deleted to notice."""
    dbx = ProbeFailsDbx(_not_found(), tree={GYP: [], COMMERCIAL: [],
                                            GYP + "/$Archive": []})
    res = _file_into(dbx, folder_path=bad)
    assert res["configured"] is False and res["error"]
    assert dbx.uploaded() == []
    assert dbx.kinds("delete") == [] and dbx.kinds("copy") == []


@pytest.mark.parametrize("good", [
    KYLES_FOLDER,                                   # category / project
    COMMERCIAL + "/*Kyle/26.06.12 Trabon Office Polish",   # category / person / project
])
def test_a_real_project_folder_at_either_depth_is_still_accepted(good):
    """The guard has to reject a category without rejecting the two shapes the live
    Dropbox actually has — Gyp is one level down, Commercial is two."""
    dbx = ProbeFailsDbx(_not_found(), tree={good: []})
    res = _file_into(dbx, folder_path=good)
    assert res["configured"] is True
    assert res["folder_path"] == good


# ═══ the route: shared wiring ═════════════════════════════════════════════════
def _wire(monkeypatch, dbx, draft_data, *, events=None, log_boom=False, saved=None):
    """Point /api/to-dropbox at `dbx` and one in-memory draft, leaving the REAL
    dropbox_client in the path so "nothing was uploaded" is a fact about the
    Dropbox calls rather than about a stubbed argument."""
    monkeypatch.setenv("DROPBOX_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(dc, "_build_client", lambda: dbx)
    monkeypatch.setattr(dc, "destination_path",
                        lambda key: {"gyp": GYP, "commercial": COMMERCIAL}.get(key))
    monkeypatch.setattr(dc, "commercial_owner_subfolder", lambda o: "")
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": draft_data})
    monkeypatch.setattr(main.drafts, "save_draft",
                        lambda i, d, **k: (saved if saved is not None else []).append(d))

    def log_event(*a, **k):
        if events is not None:
            events.append((a, k))
        if log_boom:
            raise RuntimeError("events table unreachable")

    monkeypatch.setattr(main.drafts, "log_event", log_event)
    monkeypatch.setattr(main, "_generate", lambda gi, request, persist=True: main.GenerateOut(
        work_type="gyp", audience="Direct", xlsx_download_url="/api/files/x",
        docx_download_url="/api/files/d", pdf_download_url="/api/files/d/pdf", totals={}))
    monkeypatch.setitem(main._FILE_CACHE, "x", {"content": b"xlsx-bytes"})
    monkeypatch.setitem(main._FILE_CACHE, "d", {"content": b"docx-bytes", "_pdf": b"%PDF-1.4"})
    return TestClient(main.app)


def _draft(**over):
    data = {"proposal_payload": {"work_type": "gyp", "audience": "Direct",
                                 "values": {"project_name": "Fuel House",
                                            "deadline": "2026-08-14"}}}
    data.update(over)
    return data


@pytest.fixture(autouse=True)
def _clear_folder_cache():
    dc._PROJECT_FOLDER_CACHE.clear()
    yield
    dc._PROJECT_FOLDER_CACHE.clear()


# ═══ 3. the picked folder must match the destination sent with it ═════════════
# REVERSAL: in main.api_to_dropbox, delete the
#     if existing_path and not existing_path.startswith(base_path.rstrip("/") + "/")
# block.
def test_a_gyp_folder_sent_with_commercial_selected_is_refused(monkeypatch):
    """A stale tab: the list was fetched for Gyp, the select now says Commercial.
    The files used to go into the Gyp folder while the event log recorded
    "commercial" — so the project history said something untrue about where a
    customer's paperwork went, and nothing anywhere disagreed with it."""
    dbx = RecordingDbx(tree={GYP: ["26.08.14 Fuel House"],
                             KYLES_FOLDER: ["Numbers 8.10.26"], KYLES_NUMBERS: [],
                             COMMERCIAL: []})
    events = []
    client = _wire(monkeypatch, dbx, _draft(), events=events)
    j = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "commercial",
                                             "folder_owner": "",
                                             "folder_path": KYLES_FOLDER}).json()
    assert j["ok"] is False and j["error"]
    assert dbx.uploaded() == [], "the files were filed under a contradicted request"
    assert dbx.kinds("copy") == []
    assert events == [], "a filing that never happened was written to the history"


def test_the_matching_destination_still_files(monkeypatch):
    """The guard may not cost the normal case: Commercial + a Commercial folder."""
    folder = COMMERCIAL + "/*Kyle/26.06.12 Trabon Office Polish"
    dbx = RecordingDbx(tree={COMMERCIAL: ["*Kyle"], folder: []})
    events = []
    client = _wire(monkeypatch, dbx, _draft(), events=events)
    j = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "commercial",
                                             "folder_owner": "",
                                             "folder_path": folder}).json()
    assert j["ok"] is True and j["folder_path"] == folder
    assert dbx.uploaded() and all(p.startswith(folder + "/") for p in dbx.uploaded())
    assert events, "a real filing was not recorded"
    assert events[0][0][3]["destination"] == "commercial"
    assert events[0][0][3]["folder"] == folder


def test_the_route_refuses_a_shared_bucket_inside_the_right_destination(monkeypatch):
    """Defect 2 through the real route. "$Archive" is deliberately the path here
    rather than the category itself: the category is caught twice over (it can
    never sit UNDER base_path, so the destination check above rejects it as well),
    while "$Archive" clears that check and leaves only the category rule standing.
    It is a shared bucket holding many jobs, so filing into it is the same mistake
    one level down."""
    archive = GYP + "/$Archive"
    dbx = RecordingDbx(tree={GYP: ["$Archive"], archive: []})
    client = _wire(monkeypatch, dbx, _draft())
    j = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                             "folder_path": archive}).json()
    assert j["ok"] is False and j["error"]
    assert dbx.uploaded() == [] and dbx.kinds("copy") == []


# ═══ 4. bookkeeping may not fail a filing that succeeded ══════════════════════
# REVERSAL: in main.api_to_dropbox, un-indent the drafts.log_event(...) call out
# of its try/except.
def test_a_dead_event_log_does_not_turn_a_successful_filing_into_a_failure(monkeypatch):
    """Dropbox has ALREADY accepted the files by the time the event is written. A
    500 here shows the estimator "Upload failed — please try again", and pressing
    it again files a SECOND time into Kyle's folder — the duplicate this whole
    change exists to stop, caused by the bookkeeping rather than the upload."""
    dbx = RecordingDbx(tree={GYP: ["26.08.14 Fuel House"],
                             KYLES_FOLDER: ["Numbers 8.10.26"], KYLES_NUMBERS: []})
    client = _wire(monkeypatch, dbx, _draft(), log_boom=True)
    r = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                             "folder_path": KYLES_FOLDER})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True, "a filing Dropbox accepted was reported as failed"
    assert j["folder_path"] == KYLES_FOLDER
    assert dbx.uploaded(), "the files really were uploaded"


def test_the_result_is_still_persisted_when_the_event_log_dies(monkeypatch):
    """The two writes are independent: losing the event must not cost the
    `dropbox_result` the NEXT filing reads written_paths back from."""
    dbx = RecordingDbx(tree={GYP: ["26.08.14 Fuel House"],
                             KYLES_FOLDER: ["Numbers 8.10.26"], KYLES_NUMBERS: []})
    saved = []
    client = _wire(monkeypatch, dbx, _draft(), log_boom=True, saved=saved)
    client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                         "folder_path": KYLES_FOLDER})
    assert saved and saved[-1]["dropbox_result"]["written_paths"]


# ═══ 5. the client's guard, with the escape hatch closed ══════════════════════
# REVERSAL (either half, each caught below):
#   a) frontend/js/dropbox.js dbxSyncGo: wrap the `go.disabled = …` line back up
#      in `if (!st.uploaded) { … }`   → test_the_button_goes_dead_… fails
#   b) the click handler: put back `if (dbxGoDisabled(DBX) && !DBX.uploaded) return;`
#      → test_a_forced_click_… fails
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "dropbox-page-harness.js"
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


@pytest.fixture(scope="module")
def page():
    """The whole To-Dropbox section, executed. Not a source assertion: every step
    of the sequence below is a flag set in one function, cleared in another and
    read by a third (house rule, bought on 2026-08-12)."""
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


@needs_node
def test_the_first_filing_posts_the_folder_the_estimator_picked(page):
    """The baseline the rest of the sequence hangs off: a runaway winner arrives
    armed, one click files it, and the button goes green."""
    assert page["armed"]["goDisabled"] is False
    assert page["firstClickDispatched"] is True
    assert page["postsAfterFirst"] == 1
    assert page["firstBody"]["folder_path"].endswith("/26.08.14 Fuel House")
    assert page["afterFiling"]["goLabel"].startswith("✓ Uploaded")


@needs_node
def test_the_button_goes_dead_the_moment_the_destination_changes(page):
    """The repaint half. dbxBeginLoad cleared the choice, so there is nothing to
    file into — and while `uploaded` suppressed the disabled flag the green button
    stayed live right through it, both during the fetch and after a contested list
    landed."""
    assert page["whileLoading"]["goDisabled"] is True
    assert page["clickWhileLoadingDispatched"] is False, "a live button over no choice"
    assert page["afterDestChange"]["goDisabled"] is True
    assert page["afterDestChange"]["checked"] == [], "0.90 against 0.85 armed a row"
    assert page["clickAfterDestChangeDispatched"] is False
    # The green label is kept on purpose — only `disabled` stops deferring to it.
    assert page["afterDestChange"]["goLabel"].startswith("✓ Uploaded")


@needs_node
def test_a_forced_click_with_nothing_chosen_files_nothing(page):
    """The handler's own guard, dispatched with the DOM's disabled flag ignored.
    This is the one that used to create the duplicate: the click posted with
    folder_path:"" — a deliberate "＋ Create a new folder" as far as the server is
    concerned — and made a brand-new folder in the destination just selected."""
    assert page["postsTotal"] == 1, (
        "a click with no folder chosen filed anyway: " + json.dumps(page["postBodies"]))
    assert all(p["folder_path"] for p in page["postBodies"]), (
        'folder_path:"" reached the server, which reads it as "create a new folder"')


@needs_node
def test_the_guard_is_a_guard_and_not_a_wall(page):
    """Step 5 has to stay usable: picking one of the two contested folders arms the
    button again, and the POST carries the new destination AND the folder in it."""
    assert page["afterPickingAgain"]["goDisabled"] is False
    assert page["postsAfterRepick"] == 2
    assert page["lastBody"]["destination"] == "commercial"
    assert "/$Commercial Sales Estimates/" in page["lastBody"]["folder_path"]


@needs_node
def test_a_re_upload_into_the_same_folder_still_works(page):
    """The reason the escape hatch was there. A second press after a success must
    still file — into the SAME folder, which is what "no duplicate" means here."""
    assert page["reuploadEnabled"] is True
    assert page["reuploadPosts"] == 2
    assert len(set(page["reuploadPaths"])) == 1, "the re-upload changed folder"


@needs_node
def test_a_revisit_waits_for_the_folder_list_before_it_can_file(page):
    """Coming back to a filed project restores the green button from the draft,
    before any candidate exists. It may not be live over a choice of null — and it
    arms itself once the list lands, because previous_path preselects the folder it
    went to last time."""
    assert page["revisitBeforeList"]["goDisabled"] is True
    assert page["revisitPosts"] == 0
    assert page["revisitAfterList"]["goDisabled"] is False
    assert page["revisitAfterList"]["checked"] == [
        "/2023 Treadwell Team Folder/Estimating/$Gyp Estimates/26.08.14 Fuel House"]


@needs_node
def test_the_client_mirrors_the_whole_dropbox_result_it_was_sent(page):
    """EXECUTED, where the sibling suite can only read the object literal's field
    names off the source. TW.setState PUTs the whole state blob and
    drafts.save_draft replaces `data` wholesale, so a key missing here is DELETED
    from the draft — and `written_paths` is what tells the next filing which files
    in Kyle's folder are ours to overwrite. Without it every re-send drops another
    "… (1).xlsx" in there."""
    stored = page["mirrored"]["dropbox_result"]
    for key in ("destination", "folder_owner", "folder_path", "folder_url",
                "xlsx_url", "docx_url", "pdf_url", "existing", "written_paths",
                "renamed"):
        assert key in stored, key + " is dropped from the draft on the next autosave"
    assert stored["written_paths"] == ["p"] and stored["existing"] is True
