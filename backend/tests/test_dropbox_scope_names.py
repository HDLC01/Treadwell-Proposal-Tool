"""Two scopes of one project filed to Dropbox both survive, under their own names.

RJ's split projects (drafts.py scope groups): Breakroom, Lab 1 and Lab 2 are three proposals of
"Acme HQ". Step 5 names the project FOLDER after the project, so every scope files into the same
folder, and until this change it named the FILES after the project alone. Two scopes of one work
type therefore landed on the same two paths, and the audit of this feature found two different
failures from that one cause:

  1. a folder Kyle's team made (_file_into_existing_folder): the second scope's files were taken for
     a human's and quietly autorenamed "… (1).xlsx";
  2. a folder this tool makes from the bid template (_file_into_bid_template): the uploads are
     WriteMode("overwrite"), so the second scope OVERWROTE the first scope's real estimate and
     proposal in Kyle's live Dropbox.

The fake below stores every upload's BYTES by path and honours the two write modes as Dropbox does,
so "both survive" is read back out of the store rather than inferred from a call count.
"""
from types import SimpleNamespace

import dropbox_client as dc
import main
from conftest import assert_callable_accepts
from dropbox.files import FolderMetadata
from fastapi.testclient import TestClient

_REAL_UPLOAD = dc.upload_project_files
ROOT = dc.ESTIMATING_ROOT
GYP = ROOT + "/$Gyp Estimates"


class _Meta:
    def __init__(self, path):
        self.path_display = path


class _List:
    def __init__(self, names):
        self.entries = [FolderMetadata(name=n) for n in names]
        self.cursor, self.has_more = None, False


class ConflictError(Exception):
    """Only `"conflict" in str(exc)` is read by the bid-template path."""


class ContentDbx:
    """A Dropbox that keeps what was written. `folders` maps a folder path to its child folder names;
    `content` maps a file path to its bytes. Overwrite replaces, add+autorename puts the bytes beside
    the file that is there, and copying onto a folder that exists is a conflict, as the real API."""

    def __init__(self, folders=None, content=None):
        self.folders = dict(folders or {})
        self.content = dict(content or {})

    def files_get_metadata(self, path):
        if path in self.folders:
            return FolderMetadata(name=path.rsplit("/", 1)[-1])
        if path in self.content:
            return _Meta(path)
        raise RuntimeError("not_found: " + path)

    def files_list_folder(self, path):
        if path not in self.folders:
            raise RuntimeError("not_found: " + path)
        return _List(self.folders[path])

    def files_upload(self, data, path, mode=None, autorename=False):
        real = path
        if mode == "add" and path in self.content:
            assert autorename, "an add onto an existing file without autorename is a conflict"
            stem, _, ext = path.rpartition(".")
            n = 1
            while f"{stem} ({n}).{ext}" in self.content:
                n += 1
            real = f"{stem} ({n}).{ext}"
        self.content[real] = data
        return _Meta(real)

    def files_copy_v2(self, src, dst, autorename=False):
        if dst in self.folders:
            raise ConflictError("to/conflict/folder")
        self.folders[dst] = [dc.NUMBERS_SUBFOLDER, "Docs"]
        self.folders[f"{dst}/{dc.NUMBERS_SUBFOLDER}"] = []
        self.content[f"{dst}/{dc.NUMBERS_SUBFOLDER}/{dc.TEMPLATE_ESTIMATE_NAME}"] = b"blank template"

    def files_delete_v2(self, path):
        self.content.pop(path, None)

    def sharing_create_shared_link_with_settings(self, path):
        return SimpleNamespace(url="https://www.dropbox.com/x" + path)


FAKE_DROPBOX = SimpleNamespace(files=SimpleNamespace(WriteMode=lambda m: m))

SCOPES = [("Lab 1", b"LAB1-XLSX", b"LAB1-DOCX", b"LAB1-PDF"),
          ("Lab 2", b"LAB2-XLSX", b"LAB2-DOCX", b"LAB2-PDF")]


def _common(label, x, d, p):
    return dict(project_name="Acme HQ", xlsx_bytes=x, docx_bytes=d, pdf_bytes=p,
                deadline="2026-11-02", bid_date=None, work_type="epoxy", scope_label=label)


def _assert_both_intact(dbx, results):
    paths = []
    for (label, x, d, p), res in zip(SCOPES, results):
        assert res["configured"] is True, res
        written = res["written_paths"]
        assert len(written) == 3
        est, docx, pdf = written
        assert label in est and label in docx and label in pdf, written
        assert " (1)" not in "".join(written), "a sibling was taken for a human's file and renamed"
        # READ BACK: each scope's own bytes, at each scope's own paths
        assert (dbx.content[est], dbx.content[docx], dbx.content[pdf]) == (x, d, p)
        paths += written
    assert len(set(paths)) == 6, "two scopes share a file path"


def test_two_scopes_filed_into_an_existing_folder_both_survive_under_their_own_names():
    folder = GYP + "/26.11.02 Acme HQ"
    numbers = folder + "/" + dc.NUMBERS_SUBFOLDER
    dbx = ContentDbx(folders={GYP: ["26.11.02 Acme HQ"], folder: [dc.NUMBERS_SUBFOLDER],
                              numbers: []},
                     content={numbers + "/" + dc.TEMPLATE_ESTIMATE_NAME: b"KYLE'S OWN TYPING"})
    results = [dc._file_into_existing_folder(dbx, FAKE_DROPBOX, ConflictError, FolderMetadata,
                                             folder_path=folder, **_common(*s)) for s in SCOPES]
    _assert_both_intact(dbx, results)
    assert all(r["renamed"] == [] for r in results)
    assert dbx.content[numbers + "/" + dc.TEMPLATE_ESTIMATE_NAME] == b"KYLE'S OWN TYPING"


def test_two_scopes_filed_into_a_new_folder_neither_overwrites_the_other():
    """THE WORSE ONE: the bid-template path uploads with overwrite. The second scope finds the folder
    the first one made (a conflict on the copy) and files beside it, its own names, the first scope's
    bytes untouched."""
    dbx = ContentDbx(folders={GYP: []})
    results = [dc._file_into_bid_template(dbx, FAKE_DROPBOX, ConflictError, FolderMetadata,
                                          base_path=GYP, **_common(*s)) for s in SCOPES]
    assert results[0]["existing"] is False and results[1]["existing"] is True
    assert results[0]["folder_path"] == results[1]["folder_path"], "the scopes must share the project folder"
    _assert_both_intact(dbx, results)


def test_without_a_scope_name_the_old_names_are_kept_exactly():
    """An ordinary project files under exactly the names it always did."""
    assert dc._estimate_file_name("Acme HQ") == "$ estimate sheet - Acme HQ.xlsx"
    assert dc._estimate_file_name("Acme HQ", "") == "$ estimate sheet - Acme HQ.xlsx"
    assert dc._project_proposal_name("Acme HQ", "epoxy", "2026-11-02", None) == \
        "11.02.26 TREADWELL EPOXY PROPOSAL - Acme HQ"
    assert dc._project_proposal_name("Acme HQ", "epoxy", "2026-11-02", None, "Lab 1") == \
        "11.02.26 TREADWELL EPOXY PROPOSAL - Acme HQ - Lab 1"
    assert dc._estimate_file_name("Acme HQ", "Lab 1") == "$ estimate sheet - Acme HQ - Lab 1.xlsx"


def test_a_scope_name_with_a_slash_cannot_reach_another_folder():
    assert "/" not in dc._estimate_file_name("Acme HQ", "Lab 1/../x")
    assert "/" not in dc._project_proposal_name("Acme HQ", "epoxy", None, None, "a/b")


def test_the_route_hands_the_drafts_scope_name_to_the_upload(monkeypatch):
    captured = {}
    data = {"scope_group": {"id": "g1", "label": "Lab 2"},
            "proposal_payload": {"work_type": "epoxy", "audience": "GC",
                                 "values": {"project_name": "Acme HQ", "deadline": "2026-11-02"}}}
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": data})
    monkeypatch.setattr(main.drafts, "save_draft", lambda i, d, **k: None)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main, "_stale_document_refusal", lambda d: None)
    monkeypatch.setattr(main, "_generate", lambda gi, request, persist=True: main.GenerateOut(
        work_type=gi.work_type, audience=gi.audience, xlsx_download_url="/api/files/x",
        docx_download_url="/api/files/d", pdf_download_url="/api/files/d/pdf", totals={}))
    monkeypatch.setitem(main._FILE_CACHE, "x", {"content": b"x"})
    monkeypatch.setitem(main._FILE_CACHE, "d", {"content": b"d", "_pdf": b"p"})
    monkeypatch.setattr(main.dropbox_client, "destination_path", lambda d: GYP)

    def fake_upload(**kw):
        assert_callable_accepts(_REAL_UPLOAD, kwargs=kw)
        captured.update(kw)
        return {"configured": True, "existing": False, "folder_path": GYP + "/x",
                "written_paths": [], "renamed": []}
    monkeypatch.setattr(main.dropbox_client, "upload_project_files", fake_upload)
    r = TestClient(main.app).post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp"})
    assert r.status_code == 200, r.text
    assert captured["scope_label"] == "Lab 2"
    data.pop("scope_group")
    TestClient(main.app).post("/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp"})
    assert captured["scope_label"] is None
