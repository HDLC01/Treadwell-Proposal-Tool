"""The WIRE between step 5's folder chooser and the routes that serve it.

Why this file exists as well as test_dropbox_existing_folder.py (server) and
test_dropbox_picker_ui.py (client): those two halves were built in parallel and
proved separately — the client against a hand-written fake response, the server
against a hand-written fake caller. A field name that differs by one character
passes both suites and fails the first time Kyle presses the button. Nothing was
asserting that the two agree.

So everything here is pinned to the OTHER side's actual reads/writes, by name:

  * CLIENT_READS_* / CLIENT_SENDS_POST are transcribed from
    frontend/js/dropbox.js (dbxApply, dbxFolderRow, dbxPreselect, renderResult
    and the go-button click handler). Rename a key on either side and this file
    fails loudly instead of the estimator finding out.
  * The route tests drive the REAL dropbox_client with a recording fake client,
    not a stubbed upload_project_files — the guarantees that matter here
    ("no folder was created", "nothing was deleted") are statements about which
    Dropbox API calls happen, and a stub at the upload_project_files seam cannot
    see any of them.

The stakes, per Kyle 2026-08-19: filing an estimate into the wrong customer's
folder, or clobbering a file a human wrote, is the worst outcome available in
this flow — much worse than an extra click or an extra folder.
"""
import pathlib

import dropbox_client as dc
import main
import pytest
from conftest import assert_callable_accepts
from dropbox.files import FolderMetadata
from fastapi.testclient import TestClient

ROOT = dc.ESTIMATING_ROOT
GYP = ROOT + "/$Gyp Estimates"
COMMERCIAL = ROOT + "/$Commercial Sales Estimates"

# Kyle's own folder for the job, made by hand weeks before the estimate existed.
KYLES_FOLDER = GYP + "/26.08.14 Fuel House"
KYLES_NUMBERS = KYLES_FOLDER + "/Numbers 8.10.26"
OUR_XLSX = KYLES_NUMBERS + "/$ estimate sheet - Fuel House.xlsx"


# ─── the contract, transcribed from the client ───────────────────────────────
# GET /api/dropbox/project-folders — every property dbxApply() in
# frontend/js/dropbox.js touches on the parsed body. `error` is deliberately
# absent from a healthy response (the client reads it as optional), so it is
# listed separately rather than expected in the happy-path body.
CLIENT_READS_BODY = ["folders", "previous_path", "suggested_new_name"]
CLIENT_READS_BODY_OPTIONAL = ["error"]
# Per folder: `path` is the radio's value AND the POST's folder_path, `name` and
# `parent` are rendered and filtered on, `score` drives dbxPreselect().
CLIENT_READS_FOLDER = ["name", "parent", "path", "score"]
# What the server actually sends. Pinned whole so a key the client does NOT read
# can't be dropped by one side while the other still relies on it.
SERVER_SENDS_BODY = ["base_path", "folders", "ok", "previous_path",
                     "suggested_new_name"]

# POST /api/to-dropbox — the body the click handler builds, and the fields the
# Pydantic model accepts. Pydantic IGNORES unknown fields by default, so a
# one-character difference in `folder_path` would silently drop the estimator's
# folder choice and create the duplicate this whole feature exists to prevent.
CLIENT_SENDS_POST = ["destination", "draft_id", "folder_owner", "folder_path"]
# ...and what the click handler (`ok`) and renderResult() read off a SUCCESSFUL
# response. On failure it reads `error`/`detail` instead, which a 200 never carries.
CLIENT_READS_POST = ["docx_url", "existing", "folder_path", "folder_url", "ok",
                     "pdf_url", "renamed", "xlsx_url"]
# ...plus the keys the client stores on the draft under `dropbox_result`, which
# api_to_dropbox reads back on the NEXT filing (see the test at the bottom).
SERVER_READS_BACK_FROM_DRAFT = ["folder_path", "written_paths"]


# ─── fakes ───────────────────────────────────────────────────────────────────
class _FileMeta:
    """A dropbox FileMetadata stand-in: NOT a FolderMetadata, and carrying the
    path_display that the autorename handling reads back."""

    def __init__(self, path):
        self.path_display = path


class _Link:
    """What sharing_create_shared_link_with_settings returns — _share_link reads
    `.url` off it."""

    def __init__(self, url):
        self.url = url


class _Listing:
    def __init__(self, names):
        self.entries = [FolderMetadata(name=n) for n in names]
        self.cursor = None
        self.has_more = False


class RecordingDbx:
    """A Dropbox client that records every call. `tree` maps folder path → child
    folder names; `files` is the set of file paths already there (a human's work).

    The assertions in this file are mostly about `.calls`: in a folder somebody
    else built, WHICH API calls we make is the whole safety property."""

    def __init__(self, tree=None, files=()):
        self.tree = dict(tree or {})
        self.files = set(files)
        self.calls = []

    # ── reads
    def files_get_metadata(self, path):
        self.calls.append(("get_metadata", path))
        if path in self.tree:
            return FolderMetadata(name=path.rsplit("/", 1)[-1])
        if path in self.files:
            return _FileMeta(path)
        raise RuntimeError("not_found: " + path)

    def files_list_folder(self, path):
        self.calls.append(("list_folder", path))
        if path not in self.tree:
            raise RuntimeError("not_found: " + path)
        return _Listing(self.tree[path])

    def files_list_folder_continue(self, cursor):  # pragma: no cover - unpaged fakes
        raise RuntimeError("bad_cursor: " + str(cursor))

    # ── writes
    def files_upload(self, data, path, mode=None, autorename=False):
        self.calls.append(("upload", path, mode, autorename))
        real = path
        if path in self.files and autorename:
            stem, _, ext = path.rpartition(".")
            real = stem + " (1)." + ext
        self.files.add(real)
        return _FileMeta(real)

    def files_copy_v2(self, src, dst, autorename=False):
        self.calls.append(("copy", src, dst))
        self.tree.setdefault(dst, [dc.NUMBERS_SUBFOLDER, "Docs"])
        self.tree.setdefault(dst + "/" + dc.NUMBERS_SUBFOLDER, [])
        self.files.add(dst + "/" + dc.NUMBERS_SUBFOLDER + "/" + dc.TEMPLATE_ESTIMATE_NAME)
        return None

    def files_delete_v2(self, path):
        self.calls.append(("delete", path))
        self.files.discard(path)

    def sharing_create_shared_link_with_settings(self, path):
        return _Link("https://www.dropbox.com/x" + path)

    # ── what the assertions read
    def kinds(self, kind):
        return [c for c in self.calls if c[0] == kind]

    def uploaded(self):
        return [c[1] for c in self.calls if c[0] == "upload"]


@pytest.fixture(autouse=True)
def _clear_folder_cache():
    """list_project_folders caches per base_path; a leftover entry would serve
    one test's tree to the next."""
    dc._PROJECT_FOLDER_CACHE.clear()
    yield
    dc._PROJECT_FOLDER_CACHE.clear()


def _wire(monkeypatch, dbx, draft_data, saved=None):
    """Point the routes at `dbx` and at one in-memory draft, leaving the REAL
    dropbox_client logic (validation, ranking, upload decisions) in the path."""
    monkeypatch.setenv("DROPBOX_ACCESS_TOKEN", "test-token")
    monkeypatch.setattr(dc, "_build_client", lambda: dbx)
    # destination_path normally consults the LIVE Dropbox listing first.
    monkeypatch.setattr(dc, "destination_path",
                        lambda key: {"gyp": GYP, "commercial": COMMERCIAL}.get(key))
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": draft_data})
    monkeypatch.setattr(main.drafts, "save_draft",
                        lambda i, d, **k: (saved if saved is not None else []).append(d))
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)

    def fake_generate(gi, request, persist=True, want_cover_letter=True):
        assert_callable_accepts(_real_generate, (gi, request),
                                {"persist": persist, "want_cover_letter": want_cover_letter})
        return main.GenerateOut(work_type="gyp", audience="Direct",
                                xlsx_download_url="/api/files/x",
                                docx_download_url="/api/files/d",
                                pdf_download_url="/api/files/d/pdf", totals={})

    _real_generate = main._generate
    monkeypatch.setattr(main, "_generate", fake_generate)
    monkeypatch.setitem(main._FILE_CACHE, "x", {"content": b"xlsx-bytes"})
    monkeypatch.setitem(main._FILE_CACHE, "d", {"content": b"docx-bytes",
                                                "_pdf": b"%PDF-1.4"})
    return TestClient(main.app)


def _draft(**over):
    data = {"proposal_payload": {"work_type": "gyp", "audience": "Direct",
                                 "values": {"project_name": "Fuel House",
                                            "deadline": "2026-08-14"}}}
    data.update(over)
    return data


def _kyles_tree(extra_files=()):
    """The live Gyp category holding one folder Kyle made by copying the bid
    template: a Numbers child with the blank estimate sheet still in it."""
    return RecordingDbx(
        tree={GYP: ["26.08.14 Fuel House", "$Archive", "Not Bidding"],
              KYLES_FOLDER: ["Numbers 8.10.26", "Docs"],
              KYLES_NUMBERS: [], KYLES_FOLDER + "/Docs": []},
        files=set(extra_files) | {KYLES_NUMBERS + "/" + dc.TEMPLATE_ESTIMATE_NAME},
    )


# ═══ GET /api/dropbox/project-folders — the body shape ════════════════════════
def _get_folders(client, **qs):
    qs.setdefault("destination", "gyp")
    qs.setdefault("draft_id", "d1")
    query = "&".join(k + "=" + str(v) for k, v in qs.items())
    r = client.get("/api/dropbox/project-folders?" + query)
    assert r.status_code == 200, r.text
    return r.json()


def test_the_body_holds_exactly_the_keys_the_client_reads(monkeypatch):
    """CONSUMER: frontend/js/dropbox.js, dbxApply(). Both directions are pinned —
    a key the client reads that stops being sent, and a key the server sends that
    nobody reads — because either one is a rename somebody made on one side only.
    """
    client = _wire(monkeypatch, _kyles_tree(), _draft())
    body = _get_folders(client)

    assert sorted(body) == SERVER_SENDS_BODY, (
        "the response shape changed; frontend/js/dropbox.js reads "
        + ", ".join(CLIENT_READS_BODY))
    for key in CLIENT_READS_BODY:
        assert key in body, "frontend/js/dropbox.js reads body." + key
    # `error` is absent on a healthy response ON PURPOSE: the client's note()
    # branches on its truthiness to say "the list is missing".
    for key in CLIENT_READS_BODY_OPTIONAL:
        assert key not in body, key + " must not be set when nothing went wrong"
    assert body["ok"] is True
    assert isinstance(body["folders"], list)
    assert isinstance(body["suggested_new_name"], str)


def test_each_folder_holds_exactly_the_keys_the_row_renders(monkeypatch):
    """CONSUMER: dbxFolderRow() renders name + parent, dbxMatches() filters on
    both, the radio's value is path, and dbxPreselect() compares score."""
    client = _wire(monkeypatch, _kyles_tree(), _draft())
    folders = _get_folders(client)["folders"]
    assert folders, "nothing to check"
    for f in folders:
        assert sorted(f) == CLIENT_READS_FOLDER, (
            "folder shape changed; frontend/js/dropbox.js reads "
            + ", ".join(CLIENT_READS_FOLDER))
        assert isinstance(f["name"], str) and f["name"]
        assert isinstance(f["path"], str) and f["path"].startswith(GYP + "/")
        assert isinstance(f["parent"], str)          # "" at the top level, never null
        # Number(f.score) on the client — a string here would still coerce, but a
        # null would become 0 and silently un-arm every preselection.
        assert isinstance(f["score"], (int, float)) and not isinstance(f["score"], bool)
        assert 0.0 <= f["score"] <= 1.0


def test_the_list_arrives_already_sorted_because_the_client_never_sorts_it(monkeypatch):
    """dbxPreselect() reads folders[0] and folders[1] as best and runner-up, and
    dbxFolderRow() badges folders[0] "closest match". Nothing on the client sorts,
    so the ordering is part of the contract.

    The full rule is (non-project folders last, then score descending): "$Archive"
    and "Not Bidding" stay selectable — filing into "Not Bidding" is a real thing
    somebody may want — but must never be the top suggestion."""
    client = _wire(monkeypatch, _kyles_tree(), _draft())
    folders = _get_folders(client)["folders"]
    names = [f["name"] for f in folders]
    assert names[0] == "26.08.14 Fuel House", "the client badges folders[0]"

    junk = {"$Archive", "Not Bidding"}
    projects = [f for f in folders if f["name"] not in junk]
    assert [f["score"] for f in projects] == sorted(
        (f["score"] for f in projects), reverse=True), "not best-first"
    # The non-project folders are last whatever they scored.
    assert {f["name"] for f in folders[len(projects):]} == junk


def test_previous_path_is_the_recorded_folder_the_client_preselects(monkeypatch):
    """dbxPreselect() prefers previous_path over any score: where this project was
    filed last time is a fact, a similarity score is a guess."""
    client = _wire(monkeypatch, _kyles_tree(),
                   _draft(dropbox_result={"folder_path": KYLES_FOLDER}))
    body = _get_folders(client)
    assert body["previous_path"] == KYLES_FOLDER
    # ...and it has to be findable in `folders` by === on the path, or the client
    # falls back to the score (test_a_previous_path_dropbox_no_longer_lists...).
    assert any(f["path"] == body["previous_path"] for f in body["folders"])


def test_previous_path_is_null_not_missing_when_the_project_was_never_filed(monkeypatch):
    client = _wire(monkeypatch, _kyles_tree(), _draft())
    body = _get_folders(client)
    assert "previous_path" in body and body["previous_path"] is None


def test_a_dead_dropbox_still_returns_a_body_the_client_can_render(monkeypatch):
    """Step 5 must never dead-end on somebody else's outage: the client degrades
    to create-only, and needs `error` plus `suggested_new_name` to say so."""
    dbx = RecordingDbx(tree={})          # every list_folder raises

    client = _wire(monkeypatch, dbx, _draft())
    body = _get_folders(client)
    assert body["ok"] is True
    assert body["folders"] == []
    assert body["error"], "the client's note() branches on this"
    # The create row and the note both name the folder that WOULD be made.
    assert body["suggested_new_name"] == "26.08.14 Fuel House"
    assert dbx.uploaded() == [] and dbx.kinds("copy") == []


def test_an_unknown_destination_is_still_a_renderable_body(monkeypatch):
    """The client ignores `ok` and reads `error` — so even the hard rejection has
    to carry a body dbxApply() can fold in without throwing."""
    client = _wire(monkeypatch, _kyles_tree(), _draft())
    body = _get_folders(client, destination="nope")
    assert body["ok"] is False
    assert isinstance(body["folders"], list) and body["folders"] == []
    assert isinstance(body["error"], str) and body["error"]


# ═══ POST /api/to-dropbox — the request shape ═════════════════════════════════
def test_the_model_accepts_exactly_the_fields_the_client_sends():
    """Pydantic IGNORES unknown fields. A `folder_path` renamed on one side only
    would be dropped in silence, the server would compute a folder name of its
    own, and Kyle would get the second folder again — with the page reporting
    success. That failure is the entire reason this feature exists, so the field
    NAMES are pinned here and the behaviour is pinned in the two tests below."""
    assert sorted(main.ToDropboxIn.model_fields) == CLIENT_SENDS_POST


def test_the_clients_exact_body_files_into_the_picked_folder_and_creates_nothing(monkeypatch):
    """The whole point of the feature, end to end through the real
    dropbox_client: the estimator picked Kyle's folder, so no folder may be
    created beside it."""
    dbx = _kyles_tree()
    client = _wire(monkeypatch, dbx, _draft())
    # Byte-for-byte the body frontend/js/dropbox.js builds, folder_owner ("" for a
    # non-commercial destination) included.
    r = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                             "folder_owner": "",
                                             "folder_path": KYLES_FOLDER})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["ok"] is True and j["existing"] is True
    assert j["folder_path"] == KYLES_FOLDER, "the picked folder was not honoured"
    assert dbx.kinds("copy") == [], "a second folder was created anyway"
    assert dbx.kinds("delete") == [], "something in Kyle's folder was deleted"
    assert all(p.startswith(KYLES_FOLDER + "/") for p in dbx.uploaded())


def test_a_misspelled_folder_path_is_dropped_and_creates_the_duplicate(monkeypatch):
    """The failure the name assertion above guards, made visible. Nothing errors:
    the choice vanishes, the server invents "26.08.14 Fuel House" of its own, and
    the response says it filed successfully."""
    dbx = _kyles_tree()
    client = _wire(monkeypatch, dbx, _draft())
    r = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                             "folderPath": KYLES_FOLDER})   # camelCase
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True                       # ...and it "worked"
    assert dbx.kinds("copy"), "a renamed field would have been caught by luck"


def test_the_response_holds_the_keys_renderresult_reads(monkeypatch):
    """CONSUMER: renderResult() in frontend/js/dropbox.js. `renamed` and
    `existing` are what tell the estimator a human's file was left alone."""
    dbx = _kyles_tree()
    client = _wire(monkeypatch, dbx, _draft())
    j = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                             "folder_owner": "",
                                             "folder_path": KYLES_FOLDER}).json()
    for key in CLIENT_READS_POST:
        assert key in j, "frontend/js/dropbox.js reads response." + key
    assert isinstance(j["renamed"], list)               # .filter()ed on the client
    assert isinstance(j["existing"], bool)
    # written_paths never reaches the UI, but the client stores it on the draft and
    # the server reads it back — see the round-trip test at the bottom.
    assert isinstance(j["written_paths"], list) and j["written_paths"]


# ═══ never create, never delete, never clobber ═══════════════════════════════
def test_filing_into_kyles_folder_never_deletes_the_blank_estimate_sheet(monkeypatch):
    """In a folder a human copied from the bid template, that blank
    "$ estimate sheet - 5.7.xlsx" is very likely the one Kyle has been typing his
    numbers into (Kyle 2026-08-19). The create path deletes it; this path may not.
    Asserted on the call log, because "the file is still there" would also pass if
    we deleted it and re-uploaded it."""
    dbx = _kyles_tree()
    client = _wire(monkeypatch, dbx, _draft())
    r = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                             "folder_path": KYLES_FOLDER})
    assert r.status_code == 200, r.text
    assert dbx.kinds("delete") == []
    assert KYLES_NUMBERS + "/" + dc.TEMPLATE_ESTIMATE_NAME in dbx.files


def test_a_humans_file_at_our_name_is_autorenamed_and_the_client_is_told(monkeypatch):
    """Somebody already saved a file at the exact name we file under. It must
    survive, ours must go in beside it, and the response must SAY so — an
    estimator who is not told there are now two files will send the wrong one."""
    dbx = _kyles_tree(extra_files=[OUR_XLSX])
    client = _wire(monkeypatch, dbx, _draft())
    j = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                             "folder_path": KYLES_FOLDER}).json()
    assert j["ok"] is True
    renamed = j["renamed"]
    assert renamed == [KYLES_NUMBERS + "/$ estimate sheet - Fuel House (1).xlsx"], renamed
    assert OUR_XLSX in dbx.files, "the human's file was overwritten"
    # The upload at the occupied name went in with add + autorename, not overwrite.
    ours = [c for c in dbx.calls if c[0] == "upload" and c[1] == OUR_XLSX]
    assert ours and ours[0][2].is_add() and ours[0][3] is True
    # The .docx name was free, so that one is a plain overwrite (no clutter).
    docx = [c for c in dbx.calls if c[0] == "upload" and c[1].endswith(".docx")]
    assert docx and docx[0][2].is_overwrite()


# NOT in this list, deliberately: the destination category folder itself (e.g.
# `$Gyp Estimates`). It IS accepted today — the guard only requires a path under
# the Estimating root — so a hand-rolled request could drop the estimate loose
# among the 80 project folders. The picker only ever offers a category's
# CHILDREN, so nothing in the UI can reach it, and the additive rules still hold
# (nothing created, nothing deleted, a clash autorenamed). Left as-is rather than
# tightened here, so this comment is the record rather than a passing assertion.
@pytest.mark.parametrize("bad", [
    "/Some Other Team Folder/26.08.14 Fuel House",   # outside the Estimating root
    ROOT + "/../Payroll/26.08.14 Fuel House",        # traversal
    ROOT,                                            # the Estimating root itself
    KYLES_NUMBERS + "/" + dc.TEMPLATE_ESTIMATE_NAME,  # a FILE, not a folder
])
def test_a_folder_the_picker_could_not_have_offered_is_refused_before_any_upload(monkeypatch, bad):
    """The picker only ever offers children of a destination, so any other path
    reaching this route is a stale tab, a hand-rolled request, or a bug. Refused —
    and refused BEFORE the first byte moves, which is why the call log is asserted
    rather than the response alone."""
    dbx = _kyles_tree()
    client = _wire(monkeypatch, dbx, _draft())
    j = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                             "folder_path": bad}).json()
    assert j["ok"] is False and j["error"]
    assert dbx.uploaded() == []
    assert dbx.kinds("copy") == [] and dbx.kinds("delete") == []


def test_a_folder_that_is_no_longer_there_is_refused_rather_than_created(monkeypatch):
    """Kyle renamed his folder between the listing and the click. Creating it
    would put the estimate in a folder nobody opens — the original complaint."""
    dbx = _kyles_tree()
    client = _wire(monkeypatch, dbx, _draft())
    j = client.post("/api/to-dropbox", json={
        "draft_id": "d1", "destination": "gyp",
        "folder_path": GYP + "/26.08.14 Fuel House RENAMED"}).json()
    assert j["ok"] is False
    assert dbx.uploaded() == [] and dbx.kinds("copy") == []


# ═══ the second filing: the duplicate Kyle actually saw ══════════════════════
def test_refiling_after_a_rename_reuses_the_recorded_folder(monkeypatch):
    """The other half of Kyle's duplicates. The project was filed into
    26.08.14 Fuel House, then renamed and re-dated in the tool; the old code
    computed a NEW folder name from the new values and left the first folder
    behind. With no folder_path on the request, the recorded folder wins.

    Driven through the real client so "no new folder" is a fact about the Dropbox
    calls, not about a stubbed argument."""
    dbx = _kyles_tree()
    draft = {"proposal_payload": {"work_type": "gyp", "audience": "Direct",
                                  "values": {"project_name": "Fuel House Phase 2",
                                             "deadline": "2026-09-30"}},
             "dropbox_result": {"destination": "gyp", "folder_path": KYLES_FOLDER,
                                "written_paths": [OUR_XLSX]}}
    client = _wire(monkeypatch, dbx, draft)
    j = client.post("/api/to-dropbox",
                    json={"draft_id": "d1", "destination": "gyp"}).json()
    assert j["ok"] is True
    assert j["folder_path"] == KYLES_FOLDER, "re-filing invented a second folder"
    assert dbx.kinds("copy") == [], "26.09.30 Fuel House Phase 2 was created beside it"
    assert dbx.kinds("delete") == []
    # The new name goes in under the SAME folder — that is what "no duplicate" means
    # here. (The file we wrote under the old name stays: this path never deletes
    # anything in a folder the team owns, so a rename leaves the old sheet behind.)
    assert all(p.startswith(KYLES_FOLDER + "/") for p in dbx.uploaded())
    assert any(p.endswith("$ estimate sheet - Fuel House Phase 2.xlsx")
               for p in dbx.uploaded())


def test_the_written_paths_round_trip_is_what_keeps_a_refile_from_piling_up(monkeypatch):
    """`written_paths` is written to the draft by the server and read back by the
    server, but it passes THROUGH the client: frontend/js/dropbox.js mirrors
    `dropbox_result` into TW.setState(), and shared.js PUTs the whole blob on the
    next autosave — so a partial dropbox_result there DELETES these keys from the
    draft. This pins the consequence: the same re-file, minus written_paths,
    autorenames our own estimate sheet."""
    dbx = _kyles_tree(extra_files=[OUR_XLSX])
    draft = {"proposal_payload": {"work_type": "gyp", "audience": "Direct",
                                  "values": {"project_name": "Fuel House",
                                             "deadline": "2026-08-14"}},
             # exactly what the client's setState wrote before the fix
             "dropbox_result": {"destination": "gyp", "folder_path": KYLES_FOLDER}}
    client = _wire(monkeypatch, dbx, draft)
    j = client.post("/api/to-dropbox",
                    json={"draft_id": "d1", "destination": "gyp"}).json()
    assert j["renamed"] == [KYLES_NUMBERS + "/$ estimate sheet - Fuel House (1).xlsx"], (
        "without written_paths our own file looks like a human's — this is what a "
        "partial dropbox_result on the client costs, every single send")


def test_what_the_server_persists_is_a_superset_of_what_it_reads_back(monkeypatch):
    """The keys api_to_dropbox reads off `dropbox_result` on the next filing must
    all be in what it writes there. (Whether the CLIENT keeps them is the last test
    in this file — it is the half that can silently drop them.)"""
    dbx = _kyles_tree()
    saved = []
    client = _wire(monkeypatch, dbx, _draft(), saved=saved)
    client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                         "folder_path": KYLES_FOLDER})
    assert saved, "the result was not persisted on the draft"
    stored = saved[-1]["dropbox_result"]
    for key in SERVER_READS_BACK_FROM_DRAFT:
        assert key in stored, "api_to_dropbox reads dropbox_result." + key
    assert stored["folder_path"] == KYLES_FOLDER
    assert stored["written_paths"], "nothing recorded as ours to overwrite"


# ═══ "create a new folder" is a CHOICE, not the absence of one ═══════════════
def test_choosing_create_a_new_folder_creates_one_even_after_a_previous_filing(monkeypatch):
    """"＋ Create a new folder" is the last row of the picker and a deliberate act.
    The client sends folder_path:"" for it — distinct from omitting the field —
    because the recorded-folder fallback would otherwise quietly re-file into last
    time's folder and the page would report "(the folder you picked)".

    That also un-sticks the case where the recorded folder is GONE from Dropbox:
    the fallback then fails validation and step 5 dead-ends with "couldn't find
    that folder" and no way forward."""
    dbx = _kyles_tree()
    draft = _draft(dropbox_result={"destination": "gyp", "folder_path": KYLES_FOLDER,
                                   "written_paths": [OUR_XLSX]})
    client = _wire(monkeypatch, dbx, draft)
    j = client.post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp",
                                             "folder_owner": "",
                                             "folder_path": ""}).json()
    assert j["ok"] is True
    assert dbx.kinds("copy"), "the estimator asked for a new folder and did not get one"
    assert j["existing"] is False


def test_omitting_folder_path_entirely_still_reuses_the_recorded_folder(monkeypatch):
    """The field is omitted only when the picker could not be read at all (Dropbox
    down). There was no choice to make then, so the recorded folder — not a fresh
    one — is the safer answer, and this is the guard on the distinction above."""
    dbx = _kyles_tree()
    draft = _draft(dropbox_result={"destination": "gyp", "folder_path": KYLES_FOLDER,
                                   "written_paths": [OUR_XLSX]})
    client = _wire(monkeypatch, dbx, draft)
    j = client.post("/api/to-dropbox",
                    json={"draft_id": "d1", "destination": "gyp"}).json()
    assert j["ok"] is True and j["folder_path"] == KYLES_FOLDER
    assert dbx.kinds("copy") == []


# ═══ the two client-side literals this file cannot execute ═══════════════════
# Everything above drives real code, which is the house rule (2026-08-12: a
# source-text assertion cannot see an unbound identifier). These two are the
# exception, and only because they are pure NAME checks on two object literals:
# the harness in test_dropbox_picker_ui.py lifts the picker's pure functions out
# of frontend/js/dropbox.js and cannot reach the click handler, which needs the
# whole page. So the field names in the body it POSTs, and in the state it stores,
# are read out of the source here. A name is exactly what source text can prove.
DROPBOX_JS = (pathlib.Path(__file__).resolve().parents[2]
              / "frontend" / "js" / "dropbox.js")


def _js_object_after(marker):
    """The balanced `{…}` literal that follows `marker` in dropbox.js."""
    src = DROPBOX_JS.read_text(encoding="utf-8")
    assert marker in src, "dropbox.js no longer contains: " + marker
    depth = 0
    start = src.index("{", src.index(marker))
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError("unbalanced object literal after " + marker)


def test_the_client_mirrors_every_dropbox_result_key_the_server_reads_back():
    """shared.js PUTs the WHOLE state blob and drafts.save_draft replaces `data`
    wholesale (only _SERVER_OWNED_KEYS survive), so any key missing from this
    literal is DELETED from the draft on the next autosave. `written_paths` is the
    one that costs: without it the next re-file autorenames our own estimate sheet
    instead of replacing it — see the round-trip test above."""
    block = _js_object_after("TW.setState({ dropbox_result:")
    for key in SERVER_READS_BACK_FROM_DRAFT:
        assert key + ":" in block, (
            key + " is missing from the dropbox_result frontend/js/dropbox.js "
            "stores; backend/main.py api_to_dropbox reads it back on the next filing")


def test_the_client_builds_the_post_body_out_of_the_models_field_names():
    """Read off the source rather than retyped here: CLIENT_SENDS_POST is already
    asserted against ToDropboxIn above, so this closes the loop between that list
    and the object the page actually sends."""
    block = _js_object_after("const body = { draft_id: draftId")
    for key in CLIENT_SENDS_POST:
        if key == "folder_path":
            # Set on `body` conditionally, just after the literal.
            continue
        assert key + ":" in block, key + " left the POST body in dropbox.js"
    src = DROPBOX_JS.read_text(encoding="utf-8")
    assert "body.folder_path = chosenPath" in src, (
        "the estimator's folder choice is no longer posted as folder_path")
