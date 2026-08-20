"""Step 5 files into the folder Kyle's team ALREADY made.

Kyle 2026-08-19: "use specifically the folder of dropbox and not the folders we
made. So there are duplicates there." Two separate causes, both covered here:

  1. we never offered his folder — so this adds a picker (list + rank), and a
     filing path that is purely additive: it never creates, never deletes, and
     never overwrites a file we didn't write ourselves;
  2. re-filing after the project name or the bid date changed computed a NEW
     folder name and left the first one behind. The recorded folder_path was
     written to the draft and never read back.

The fakes below record every call, because what matters in a folder somebody
else built is exactly which API calls we make in it.
"""
from types import SimpleNamespace

import dropbox_client as dc
import main
import pytest
from conftest import assert_callable_accepts
from dropbox.files import FolderMetadata
from fastapi.testclient import TestClient

# The real callables, captured before any test monkeypatches the names. The doubles
# below take **kw (they have to, to record the call), so they bind what they were
# handed against these: neither function has a **kwargs of its own, which makes a
# keyword they don't declare a TypeError in production and a green test here.
_REAL_UPLOAD = dc.upload_project_files
_REAL_FILE_INTO_EXISTING = dc._file_into_existing_folder

ROOT = dc.ESTIMATING_ROOT
GYP = ROOT + "/$Gyp Estimates"
COMMERCIAL = ROOT + "/$Commercial Sales Estimates"


# ── fakes ────────────────────────────────────────────────────────────────────
class _FileMeta:
    """Stands in for dropbox FileMetadata: deliberately NOT a FolderMetadata, and
    carries the path_display our autorename handling reads back."""
    def __init__(self, path):
        self.path_display = path


class _Res:
    def __init__(self, names, cursor=None, has_more=False):
        self.entries = [FolderMetadata(name=n) for n in names]
        self.cursor = cursor
        self.has_more = has_more


class FakeDbx:
    """`tree` maps a folder path → its child folder names. `files` is the set of
    file paths already sitting in Dropbox (a human's work). Every call lands in
    `.calls`, which is what the "we never delete" assertions read."""

    def __init__(self, tree=None, files=(), pages=None, copy_error=None):
        self.tree = dict(tree or {})
        self.files = set(files)
        self.pages = dict(pages or {})     # path → [(names, cursor, has_more), …]
        self.copy_error = copy_error
        self.calls = []

    # ── reads
    def files_get_metadata(self, path):
        self.calls.append(("get_metadata", path))
        if path in self.tree:
            return FolderMetadata(name=path.rsplit("/", 1)[-1])
        if path in self.files:
            return _FileMeta(path)
        raise RuntimeError(f"not_found: {path}")

    def files_list_folder(self, path):
        self.calls.append(("list_folder", path))
        if path in self.pages:
            names, cursor, has_more = self.pages[path][0]
            return _Res(names, cursor, has_more)
        if path not in self.tree:
            raise RuntimeError(f"not_found: {path}")
        return _Res(self.tree[path])

    def files_list_folder_continue(self, cursor):
        self.calls.append(("list_folder_continue", cursor))
        for path, pages in self.pages.items():
            for i, (_, cur, _hm) in enumerate(pages):
                if cur == cursor:
                    names, nxt, has_more = pages[i + 1]
                    return _Res(names, nxt, has_more)
        raise RuntimeError(f"bad_cursor: {cursor}")

    # ── writes
    def files_upload(self, data, path, mode=None, autorename=False):
        self.calls.append(("upload", path, mode, autorename))
        real = path
        if path in self.files and autorename:
            stem, _, ext = path.rpartition(".")
            real = f"{stem} (1).{ext}"
        self.files.add(real)
        return _FileMeta(real)

    def files_copy_v2(self, src, dst, autorename=False):
        self.calls.append(("copy", src, dst))
        if self.copy_error:
            raise self.copy_error
        self.tree.setdefault(dst, [dc.NUMBERS_SUBFOLDER, "Docs"])
        self.tree.setdefault(f"{dst}/{dc.NUMBERS_SUBFOLDER}", [])
        self.files.add(f"{dst}/{dc.NUMBERS_SUBFOLDER}/{dc.TEMPLATE_ESTIMATE_NAME}")
        return None

    def files_delete_v2(self, path):
        self.calls.append(("delete", path))
        self.files.discard(path)

    def sharing_create_shared_link_with_settings(self, path):
        return SimpleNamespace(url="https://www.dropbox.com/x" + path)

    # ── helpers for the assertions
    def uploaded(self):
        return [c[1] for c in self.calls if c[0] == "upload"]

    def deletes(self):
        return [c for c in self.calls if c[0] == "delete"]


class FakeApiError(Exception):
    """Only the message is inspected (`"conflict" in str(exc)`), so a plain
    Exception subclass is a faithful stand-in for dropbox's ApiError."""


# `dropbox.files.WriteMode(...)` → the bare string, so a test can assert the mode.
FAKE_DROPBOX = SimpleNamespace(files=SimpleNamespace(WriteMode=lambda m: m))


def _file_into(dbx, **kw):
    kw.setdefault("project_name", "Fuel House")
    kw.setdefault("xlsx_bytes", b"xlsx")
    kw.setdefault("docx_bytes", b"docx")
    kw.setdefault("pdf_bytes", None)
    kw.setdefault("deadline", "2026-08-14")
    kw.setdefault("bid_date", None)
    kw.setdefault("work_type", "gyp")
    return dc._file_into_existing_folder(dbx, FAKE_DROPBOX, FakeApiError, FolderMetadata, **kw)


# ── folder_match_key ─────────────────────────────────────────────────────────
def test_match_key_strips_a_date_prefix_but_never_a_street_number():
    """"2101 Broadway" and "8036 Metcalf Apts" are real *RJ folders. A regex that
    just ate leading digits would match them against every other numbered job."""
    assert dc.folder_match_key("26.06.12 Trabon Office Polish") == "trabon office polish"
    assert dc.folder_match_key("2101 Broadway") == "2101 broadway"
    assert dc.folder_match_key("8036 Metcalf Apts") == "8036 metcalf apts"


def test_match_key_handles_every_date_form_the_folders_use():
    assert dc.folder_match_key("2026-08-21 Fuel House") == "fuel house"
    assert dc.folder_match_key("08.21.26 Fuel House") == "fuel house"      # MM.DD.YY
    assert dc.folder_match_key("26.08.21 Fuel House") == "fuel house"      # YY.MM.DD
    # A dotted group that isn't a real date is left alone.
    assert dc.folder_match_key("26.13.45 Weird") == "26 13 45 weird"
    # Punctuation dropped, whitespace collapsed (a live $Plans Specs name).
    assert dc.folder_match_key("26.08.21 MCI1-Pilot De Soto, KS - IFP B02") == \
        "mci1 pilot de soto ks ifp b02"
    assert dc.folder_match_key("") == ""
    assert dc.folder_match_key(None) == ""


# ── ranking ──────────────────────────────────────────────────────────────────
# The REAL contents of $Commercial Sales Estimates/*Kyle, all 27 entries, read
# live (read-only files_list_folder) on 2026-08-20 — not stand-ins. The earlier
# version of this fixture was 4 measured names plus ~17 invented ones, which
# meant "the true match ranks first" was measured against fiction and the
# weights were tuned to it. These are Kyle's actual folders, so a weight change
# that would misrank his real jobs fails here.
#
# Worth knowing about the shape of this data, because it is what the ranking has
# to survive: three of the 27 are not projects at all ("*Archive",
# "*MeasureSquare", "*Stack"), and the project names carry parentheticals
# ("(2026)"), ampersands, abbreviations nobody expands ("FBCBS", "PSU OP",
# "CONF MTZ"), a typo Kyle has not fixed ("Bradley Amimal Hospital"), and one
# name long enough to swamp a similarity ratio (Tyson Foods, 63 chars).
_KYLE_LISTING = [
    "*Archive", "*MeasureSquare", "*Stack",
    "26.05.20 Shasta Beverage (2026)",
    "26.06.01 Bradley Amimal Hospital",
    "26.06.03 Alltrista",
    "26.06.12 Trabon Office Polish",          # the true match for "Trabon Group"
    "26.06.18 715 Restaurant",
    "26.06.19 FBCBS 2026",
    "26.06.24 Mellow Fellow",
    "26.06.30 Niagara Bottling",
    "26.07.07 Flora Ceres",
    "26.07.10 CONF MTZ Edgerton KS",
    "26.07.10 MB Polymer Mixing T&S Project",
    "26.07.13 Collins Webb Architecture",
    "26.07.13 Sigma Estimating LLC",
    "26.07.14 Nearman Creek Power Station",
    "26.07.16 Tyson Foods KC - Resinous Flooring and Line Striping",
    "26.07.17 Adler Pelzer",
    "26.07.17 Textron - Plant 1 Tube Assembly",
    "26.07.22 Power Sales and Advertising",
    "26.07.31 American Ceramics",
    "26.08.07 PSU OP Office",
    "26.08.17 Rethink KC",
    "26.08.18 Riverview Elem. Scratch Repair",
    "26.08.19 ACI Plastics",
    "26.08.19 Stowers Stern Reno",
]

# The one SYNTHETIC entry, kept separate from the live listing above so the two
# never get confused again. Nothing in Kyle's real folder competes with
# "Trabon Group" on the distinctive token, so the live data alone cannot tell us
# whether that term is load-bearing or merely along for the ride. This name
# shares only the generic word "group" and is textually CLOSER, so string
# similarity + Jaccard on their own rank it ABOVE the real match — the
# distinctive-token term is the only thing that separates them.
_ADVERSARIAL_NEAR_MISS = "26.02.01 Trailhead Group"


def _ranked(names, project, parent=""):
    folders = [{"name": n, "path": f"{COMMERCIAL}/*Kyle/{n}", "parent": parent}
               for n in names]
    return dc.rank_project_folders(folders, project)


def test_trabon_group_finds_trabon_office_polish():
    """The pair that made this feature necessary. The only shared signal is the
    token "trabon" — Jaccard on the word sets scores it 0.25, which is why the
    distinctive-token term exists."""
    # The live listing PLUS the one synthetic near-miss: Kyle's real folders give
    # the winner 26 real competitors, and the near-miss is what proves the
    # distinctive-token term is load-bearing rather than decorative.
    ranked = _ranked(_KYLE_LISTING + [_ADVERSARIAL_NEAR_MISS], "Trabon Group")
    assert ranked[0]["name"] == "26.06.12 Trabon Office Polish"
    best = ranked[0]["score"]
    for f in ranked[1:]:
        assert f["score"] < best, f"{f['name']} tied or beat the real match"
    # Specifically ahead of the near-miss that wins on string similarity alone.
    runner_up = next(f for f in ranked if f["name"] == _ADVERSARIAL_NEAR_MISS)
    assert runner_up["score"] < best


def test_ranking_keeps_every_folder_and_scores_are_in_range():
    ranked = _ranked(_KYLE_LISTING, "Trabon Group")
    assert len(ranked) == len(_KYLE_LISTING)
    assert {f["name"] for f in ranked} == set(_KYLE_LISTING)
    assert all(0.0 <= f["score"] <= 1.0 for f in ranked)


def test_archive_and_not_bidding_sort_last_even_when_they_score_high():
    """Filing into "Not Bidding" is a real thing somebody may want, so these stay
    selectable — they just must never be the top suggestion."""
    names = ["*Stack", "Not Bidding", "26.06.12 Trabon Office Polish",
             "$Archive", "Greg- Archive", "*MeasureSquare", "_Kyle"]
    ranked = _ranked(names, "Stack Archive")           # deliberately adversarial
    assert ranked[0]["name"] == "26.06.12 Trabon Office Polish"
    junk = [f for f in ranked[1:]]
    assert {f["name"] for f in junk} == set(names) - {"26.06.12 Trabon Office Polish"}
    # Score alone WOULD have put them first — that's what the ordering overrides.
    assert max(f["score"] for f in junk) > ranked[0]["score"]


def test_ranking_is_stable_for_equal_scores():
    names = ["26.01.01 Alpha", "26.01.02 Bravo", "26.01.03 Charlie"]
    ranked = _ranked(names, "")                 # no project name → every score 0
    assert [f["name"] for f in ranked] == names


# ── list_project_folders ─────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _clear_project_folder_cache():
    dc._PROJECT_FOLDER_CACHE.clear()
    yield
    dc._PROJECT_FOLDER_CACHE.clear()


def _commercial_dbx():
    return FakeDbx(tree={
        COMMERCIAL + "/*Kyle": ["26.06.12 Trabon Office Polish", "*Archive"],
        COMMERCIAL + "/_Kyle": ["26.06.12 Trabon Office Polish"],   # sync twin (a ghost)
        COMMERCIAL + "/*RJ": ["2101 Broadway"],
    }, pages={
        # Paginated on purpose: 67-80 children is normal in these categories.
        COMMERCIAL: [(["*Kyle", "_Kyle"], "cur1", True), (["*RJ"], None, False)],
    })


def test_commercial_listing_descends_into_the_star_folder_not_the_sync_twin(monkeypatch):
    """$Commercial Sales Estimates holds NO project folders — only *Hanz *Kyle
    *Liz *RJ *Troy and Dropbox's "_Name" Windows-sync renames of them. Descending
    is the only way Kyle's folders are reachable; descending into the twin would
    file into a ghost."""
    dbx = _commercial_dbx()
    monkeypatch.setattr(dc, "_build_client", lambda: dbx)
    got = dc.list_project_folders(COMMERCIAL, include_owner_subfolders=True)

    by_path = {f["path"]: f for f in got}
    assert COMMERCIAL + "/*Kyle/26.06.12 Trabon Office Polish" in by_path
    assert by_path[COMMERCIAL + "/*Kyle/26.06.12 Trabon Office Polish"]["parent"] == "*Kyle"
    assert COMMERCIAL + "/*RJ/2101 Broadway" in by_path        # second page
    assert not any("/_Kyle/" in p for p in by_path)
    assert ("list_folder", COMMERCIAL + "/_Kyle") not in dbx.calls
    # The owner folders themselves are still listed (parent "") — they rank last.
    assert by_path[COMMERCIAL + "/*Kyle"]["parent"] == ""


def test_listing_does_not_descend_unless_asked(monkeypatch):
    dbx = _commercial_dbx()
    monkeypatch.setattr(dc, "_build_client", lambda: dbx)
    got = dc.list_project_folders(COMMERCIAL)
    assert [f["name"] for f in got] == ["*Kyle", "_Kyle", "*RJ"]
    assert not any(c[0] == "list_folder" and c[1] != COMMERCIAL for c in dbx.calls)


def test_listing_is_cached_per_base_path_and_flag(monkeypatch):
    dbx = _commercial_dbx()
    monkeypatch.setattr(dc, "_build_client", lambda: dbx)
    dc.list_project_folders(COMMERCIAL, include_owner_subfolders=True)
    n = len(dbx.calls)
    dc.list_project_folders(COMMERCIAL, include_owner_subfolders=True)
    assert len(dbx.calls) == n, "second call re-hit Dropbox"
    dc.list_project_folders(COMMERCIAL)          # different flag → different key
    assert len(dbx.calls) > n


# ── filing into an existing folder ───────────────────────────────────────────
FOLDER = GYP + "/26.08.14 Fuel House"
NUMBERS = FOLDER + "/Numbers 8.10.26"
EST = NUMBERS + "/$ estimate sheet - Fuel House.xlsx"


def _human_folder(extra_files=()):
    """A folder a human made by copying the bid template: a Numbers subfolder
    with the blank template sheet still in it."""
    return FakeDbx(
        tree={FOLDER: ["Numbers 8.10.26", "Docs"], NUMBERS: [], FOLDER + "/Docs": []},
        files=set(extra_files) | {NUMBERS + "/" + dc.TEMPLATE_ESTIMATE_NAME},
    )


def test_filing_into_a_human_folder_never_deletes_anything():
    """The blank "$ estimate sheet" in a folder a human copied from the template
    is very likely the one Kyle has been typing his numbers into. The create path
    deletes it; this path must not, ever."""
    dbx = _human_folder()
    res = _file_into(dbx, folder_path=FOLDER, pdf_bytes=b"pdf")
    assert res["configured"] is True and res["existing"] is True
    assert dbx.deletes() == []
    assert NUMBERS + "/" + dc.TEMPLATE_ESTIMATE_NAME in dbx.files
    assert res["folder_path"] == FOLDER          # we did NOT invent a folder name
    assert len(res["written_paths"]) == 3        # xlsx + docx + pdf
    assert res["renamed"] == []


def test_a_file_already_at_our_name_is_added_beside_not_overwritten():
    dbx = _human_folder(extra_files=[EST])
    res = _file_into(dbx, folder_path=FOLDER)
    add = [c for c in dbx.calls if c[0] == "upload" and c[1] == EST]
    assert add and add[0][2] == "add" and add[0][3] is True
    assert res["written_paths"][0] == NUMBERS + "/$ estimate sheet - Fuel House (1).xlsx"
    assert res["renamed"] == [res["written_paths"][0]]
    assert EST in dbx.files                      # the human's copy is still there
    # The .docx name was free, so that one is a plain overwrite.
    docx = [c for c in dbx.calls if c[0] == "upload" and c[1].endswith(".docx")]
    assert docx[0][2] == "overwrite"


def test_our_own_earlier_file_is_overwritten_cleanly():
    """Without known_paths a re-file would pile up "… (1).xlsx" every time."""
    dbx = _human_folder(extra_files=[EST])
    res = _file_into(dbx, folder_path=FOLDER, known_paths=(EST,))
    assert res["written_paths"][0] == EST
    assert res["renamed"] == []
    est_calls = [c for c in dbx.calls if c[0] == "upload" and c[1] == EST]
    assert est_calls[0][2] == "overwrite" and est_calls[0][3] is False
    assert dbx.deletes() == []


def test_no_numbers_child_files_into_the_folder_root():
    """The *RJ folders don't follow the bid-template shape. files_upload creates
    missing parents, so falling back to the NUMBERS_SUBFOLDER constant here would
    invent a stray "Numbers …" folder inside somebody's project folder."""
    plain = COMMERCIAL + "/*RJ/2101 Broadway"
    dbx = FakeDbx(tree={plain: ["Photos"]})
    res = _file_into(dbx, folder_path=plain, project_name="2101 Broadway")
    assert res["written_paths"][0] == plain + "/$ estimate sheet - 2101 Broadway.xlsx"
    assert not any("Numbers" in p for p in dbx.uploaded())
    assert dc.NUMBERS_SUBFOLDER not in "".join(dbx.uploaded())
    assert dbx.deletes() == []


def test_an_existing_numbers_child_is_used_whatever_its_version():
    dbx = FakeDbx(tree={FOLDER: ["Numbers 1.20.26"], FOLDER + "/Numbers 1.20.26": []})
    res = _file_into(dbx, folder_path=FOLDER)
    assert res["written_paths"][0].startswith(FOLDER + "/Numbers 1.20.26/")


@pytest.mark.parametrize("bad", [
    "/Some Other Team Folder/26.08.14 Fuel House",     # outside Estimating
    ROOT + "/../Payroll/26.08.14 Fuel House",          # traversal
    ROOT,                                              # the category root itself
    "",
    # A CATEGORY folder. It is one segment under the Estimating root, so the
    # startswith test clears it on its own, and $Gyp Estimates holds 80 real
    # project folders — filing here drops one customer's estimate loose in the
    # folder the whole team shares.
    GYP,
    # A shared bucket inside a category, refused by the "$" leaf rule.
    GYP + "/$Archive",
    # A PERSON folder. Two segments deep, so the length test clears it too —
    # this is the case the length test alone misses. *Kyle holds his 27 jobs, so
    # filing here is the category mistake one level down.
    COMMERCIAL + "/*Kyle",
    # ...and the non-project folders that live beside those jobs.
    COMMERCIAL + "/*Kyle/*Archive",
    COMMERCIAL + "/*Kyle/*MeasureSquare",
])
def test_a_path_we_cannot_vouch_for_is_refused(bad):
    dbx = _human_folder()
    res = _file_into(dbx, folder_path=bad)
    assert res["configured"] is False
    assert dbx.uploaded() == [] and dbx.deletes() == []


def test_a_missing_folder_is_refused_rather_than_created():
    dbx = _human_folder()
    res = _file_into(dbx, folder_path=GYP + "/26.08.14 Renamed By Kyle")
    assert res["configured"] is False
    assert "renamed" in res["error"].lower() or "find" in res["error"].lower()
    assert dbx.uploaded() == []


def test_a_file_path_is_not_a_folder():
    dbx = _human_folder()
    res = _file_into(dbx, folder_path=NUMBERS + "/" + dc.TEMPLATE_ESTIMATE_NAME)
    assert res["configured"] is False and dbx.uploaded() == []


# ── the create path still cleans up after ITSELF ─────────────────────────────
def _create(dbx, **kw):
    kw.setdefault("base_path", GYP)
    kw.setdefault("project_name", "Fuel House")
    kw.setdefault("xlsx_bytes", b"xlsx")
    kw.setdefault("docx_bytes", b"docx")
    kw.setdefault("pdf_bytes", None)
    kw.setdefault("deadline", "2026-08-14")
    kw.setdefault("bid_date", None)
    kw.setdefault("work_type", "gyp")
    return dc._file_into_bid_template(dbx, FAKE_DROPBOX, FakeApiError, FolderMetadata, **kw)


def test_create_path_deletes_the_blank_sheet_it_just_copied():
    dbx = FakeDbx(tree={GYP: []})
    res = _create(dbx)
    assert res["existing"] is False
    assert ("delete", FOLDER + f"/{dc.NUMBERS_SUBFOLDER}/{dc.TEMPLATE_ESTIMATE_NAME}") \
        in dbx.calls
    assert res["written_paths"] and res["renamed"] == []


def test_create_path_does_not_delete_when_the_folder_was_already_there():
    """files_copy_v2 raising a conflict means the folder EXISTS — quite possibly
    one a human made from the same template, whose blank sheet holds his numbers.
    The delete used to run regardless of whether the copy happened."""
    dbx = FakeDbx(tree={GYP: [], FOLDER: ["Numbers 8.10.26"], NUMBERS: []},
                  files={NUMBERS + "/" + dc.TEMPLATE_ESTIMATE_NAME},
                  copy_error=FakeApiError("path/conflict/folder/..."))
    res = _create(dbx)
    assert res["existing"] is True
    assert dbx.deletes() == []
    assert NUMBERS + "/" + dc.TEMPLATE_ESTIMATE_NAME in dbx.files


def test_a_non_conflict_copy_error_still_raises():
    dbx = FakeDbx(tree={GYP: []}, copy_error=FakeApiError("insufficient_space"))
    with pytest.raises(FakeApiError):
        _create(dbx)


# ── upload_project_files routing ─────────────────────────────────────────────
def test_existing_folder_path_wins_over_base_path(monkeypatch):
    monkeypatch.setenv("DROPBOX_ACCESS_TOKEN", "t")
    seen = {}

    def spy(dbx, dropbox, ApiError, FolderMetadata, **kw):
        assert_callable_accepts(_REAL_FILE_INTO_EXISTING,
                                args=(dbx, dropbox, ApiError, FolderMetadata), kwargs=kw)
        seen.update(kw)
        return {"configured": True, "existing": True}

    monkeypatch.setattr(dc, "_build_client", lambda: FakeDbx())
    monkeypatch.setattr(dc, "_file_into_existing_folder", spy)
    monkeypatch.setattr(dc, "_file_into_bid_template",
                        lambda *a, **k: pytest.fail("created a folder anyway"))
    out = dc.upload_project_files(project_name="Fuel House", xlsx_bytes=b"x", docx_bytes=b"d",
                                  base_path=GYP, existing_folder_path=FOLDER,
                                  known_paths=[EST])
    assert out["existing"] is True
    assert seen["folder_path"] == FOLDER and seen["known_paths"] == [EST]


# ── /api/to-dropbox: the recorded folder is read back ────────────────────────
def _stub_to_dropbox(monkeypatch, draft_data, captured, saved=None):
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": draft_data})
    monkeypatch.setattr(main.drafts, "save_draft",
                        lambda i, d, **k: (saved if saved is not None else []).append(d))
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main, "_generate", lambda gi, request, persist=True: main.GenerateOut(
        work_type="gyp", audience="Direct", xlsx_download_url="/api/files/x",
        docx_download_url="/api/files/d", pdf_download_url="/api/files/d/pdf", totals={}))
    monkeypatch.setitem(main._FILE_CACHE, "x", {"content": b"xlsx"})
    monkeypatch.setitem(main._FILE_CACHE, "d", {"content": b"docx", "_pdf": b"%PDF-1.4"})
    monkeypatch.setattr(main.dropbox_client, "destination_path",
                        lambda d: {"gyp": GYP, "commercial": COMMERCIAL}.get(d))
    monkeypatch.setattr(main.dropbox_client, "commercial_owner_subfolder", lambda o: "")

    def fake_upload(**kw):
        assert_callable_accepts(_REAL_UPLOAD, kwargs=kw)
        captured.update(kw)
        return {"configured": True, "existing": bool(kw.get("existing_folder_path")),
                "folder_path": kw.get("existing_folder_path") or GYP + "/26.09.01 Renamed",
                "folder_url": "https://dropbox/x",
                "written_paths": [EST], "renamed": []}

    monkeypatch.setattr(main.dropbox_client, "upload_project_files", fake_upload)


def _renamed_draft():
    """A project that was filed once, then renamed + re-dated in the tool — the
    exact case that used to leave a second folder behind."""
    return {
        "proposal_payload": {"work_type": "gyp", "audience": "Direct",
                             "values": {"project_name": "Fuel House Phase 2",
                                        "deadline": "2026-09-01"}},
        "dropbox_result": {"destination": "gyp", "folder_owner": None,
                           "folder_path": FOLDER, "written_paths": [EST]},
    }


def test_second_filing_reuses_the_recorded_folder(monkeypatch):
    captured, saved = {}, []
    _stub_to_dropbox(monkeypatch, _renamed_draft(), captured, saved)
    r = TestClient(main.app).post("/api/to-dropbox",
                                  json={"draft_id": "d1", "destination": "gyp"})
    assert r.status_code == 200, r.text
    assert captured["existing_folder_path"] == FOLDER, \
        "re-filing computed a new folder name and left the first folder behind"
    assert captured["known_paths"] == (EST,)      # our own file, ours to overwrite
    assert r.json()["folder_path"] == FOLDER
    assert saved[-1]["dropbox_result"]["written_paths"] == [EST]
    assert saved[-1]["dropbox_result"]["existing"] is True


def test_an_explicitly_picked_folder_beats_the_recorded_one(monkeypatch):
    captured = {}
    _stub_to_dropbox(monkeypatch, _renamed_draft(), captured)
    picked = GYP + "/26.07.30 Fuel House Kyle"
    r = TestClient(main.app).post("/api/to-dropbox", json={
        "draft_id": "d1", "destination": "gyp", "folder_path": picked})
    assert r.status_code == 200, r.text
    assert captured["existing_folder_path"] == picked
    assert captured["known_paths"] == ()          # a folder we've never written in


def test_switching_destination_files_afresh(monkeypatch):
    """The recorded folder is only reused when it still sits under the
    destination now selected — otherwise the estimator deliberately moved it."""
    captured = {}
    _stub_to_dropbox(monkeypatch, _renamed_draft(), captured)
    r = TestClient(main.app).post("/api/to-dropbox",
                                  json={"draft_id": "d1", "destination": "commercial"})
    assert r.status_code == 200, r.text
    assert captured["existing_folder_path"] is None
    assert captured["base_path"] == COMMERCIAL


def test_a_first_filing_still_creates(monkeypatch):
    captured = {}
    data = {"proposal_payload": {"work_type": "gyp", "audience": "Direct",
                                 "values": {"project_name": "Fuel House"}}}
    _stub_to_dropbox(monkeypatch, data, captured)
    r = TestClient(main.app).post("/api/to-dropbox",
                                  json={"draft_id": "d1", "destination": "gyp"})
    assert r.status_code == 200, r.text
    assert captured["existing_folder_path"] is None and captured["base_path"] == GYP


# ── /api/dropbox/project-folders ─────────────────────────────────────────────
def _stub_picker(monkeypatch, draft_data, folders=None, boom=False):
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": draft_data})
    monkeypatch.setattr(main.dropbox_client, "destination_path",
                        lambda d: {"gyp": GYP, "commercial": COMMERCIAL}.get(d))
    monkeypatch.setattr(main.dropbox_client, "commercial_owner_subfolder", lambda o: "")

    def listing(base_path, *, include_owner_subfolders=False):
        if boom:
            raise RuntimeError("dropbox unreachable")
        listing.seen = (base_path, include_owner_subfolders)
        return [{"name": n, "path": f"{base_path}/{n}", "parent": ""} for n in (folders or [])]

    monkeypatch.setattr(main.dropbox_client, "list_project_folders", listing)
    return listing


def test_picker_ranks_the_live_folders_and_offers_a_new_name(monkeypatch):
    data = {"proposal_payload": {"work_type": "gyp", "audience": "Direct",
                                 "values": {"project_name": "Trabon Group",
                                            "deadline": "2026-09-01"}},
            "dropbox_result": {"folder_path": FOLDER}}
    _stub_picker(monkeypatch, data, folders=_KYLE_LISTING)
    j = TestClient(main.app).get(
        "/api/dropbox/project-folders?destination=gyp&draft_id=d1").json()
    assert j["ok"] is True
    assert j["folders"][0]["name"] == "26.06.12 Trabon Office Polish"
    assert j["suggested_new_name"] == "26.09.01 Trabon Group"
    assert j["previous_path"] == FOLDER
    assert j["base_path"] == GYP


def test_picker_reads_the_name_of_an_older_draft_with_no_proposal_payload(monkeypatch):
    """The common existing-project case — and the one Kyle is filing. Reading the
    name only from proposal_payload would rank every folder against "" ."""
    _stub_picker(monkeypatch, {"project_name": "Trabon Group", "deadline": "2026-09-01",
                               "sqft": 4200}, folders=_KYLE_LISTING)
    j = TestClient(main.app).get(
        "/api/dropbox/project-folders?destination=gyp&draft_id=d1").json()
    assert j["folders"][0]["name"] == "26.06.12 Trabon Office Polish"
    assert j["suggested_new_name"] == "26.09.01 Trabon Group"


def test_picker_descends_for_commercial_only_when_no_person_is_chosen(monkeypatch):
    data = {"project_name": "Trabon Group", "sqft": 1}
    listing = _stub_picker(monkeypatch, data, folders=[])
    c = TestClient(main.app)
    c.get("/api/dropbox/project-folders?destination=commercial&draft_id=d1")
    assert listing.seen == (COMMERCIAL, True)
    c.get("/api/dropbox/project-folders?destination=gyp&draft_id=d1")
    assert listing.seen == (GYP, False)


def test_picker_never_dead_ends_when_dropbox_is_down(monkeypatch):
    _stub_picker(monkeypatch, {"project_name": "Trabon Group", "sqft": 1}, boom=True)
    j = TestClient(main.app).get(
        "/api/dropbox/project-folders?destination=gyp&draft_id=d1").json()
    assert j["ok"] is True and j["folders"] == []
    assert j["error"] and j["suggested_new_name"].endswith("Trabon Group")
