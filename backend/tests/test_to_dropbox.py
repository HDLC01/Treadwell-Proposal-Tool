"""Step-5 'To Dropbox': destination map + the simple YY.MM.DD folder convention.

These cover the NEW behavior only; the existing folder/filename conventions are
pinned by test_dropbox_naming.py and the graceful-degradation contract by
test_security_misc.py (both left untouched).

The route-level section at the bottom pins the HAND-OFF: /api/to-dropbox is the
only place the upload's arguments are assembled, and every one of them is a
decision the estimator made."""
import re

import dropbox_client as dc
import main
from conftest import assert_callable_accepts
from fastapi.testclient import TestClient

# The real upload, captured before any test monkeypatches the name.
_REAL_UPLOAD = dc.upload_project_files


def test_destination_map_has_three_with_verified_paths():
    d = dc.ESTIMATING_DESTINATIONS
    assert set(d) == {"gyp", "plans_specs", "commercial"}
    assert d["gyp"].endswith("/$Gyp Estimates")
    assert d["plans_specs"].endswith("/$Plans Specs Estimates")
    # Commercial Sales files into the CATEGORY folder itself (Hanz 2026-07-14:
    # not into the per-person *Kyle sub-folder).
    assert d["commercial"].endswith("/$Commercial Sales Estimates")
    assert "*Kyle" not in d["commercial"]
    for p in d.values():
        assert p.startswith("/2023 Treadwell Team Folder/Estimating/")


def test_commercial_owner_subfolders(monkeypatch):
    # FALLBACK list only — the live set now comes from list_estimating_folders().
    # Liz and Troy were dropped per Will. Stub the live call so this test pins the
    # fallback rather than whatever Dropbox currently holds.
    monkeypatch.setattr(dc, "list_estimating_folders",
                        lambda: (_ for _ in ()).throw(RuntimeError("offline")))
    assert dc.COMMERCIAL_OWNER_SUBFOLDERS == {"kyle": "*Kyle", "hanz": "*Hanz", "rj": "*RJ"}
    assert dc.commercial_owner_subfolder("Kyle") == "*Kyle"     # case-insensitive
    assert dc.commercial_owner_subfolder("  rj ") == "*RJ"      # trimmed
    assert dc.commercial_owner_subfolder("") == ""             # blank → category folder
    assert dc.commercial_owner_subfolder(None) == ""           # none → category folder
    assert dc.commercial_owner_subfolder("nobody") == ""       # unknown → category folder
    # the base commercial destination stays the category root (no *Name baked in)
    assert "*" not in dc.ESTIMATING_DESTINATIONS["commercial"]


def test_simple_folder_path_is_date_space_name_no_marker():
    base = dc.ESTIMATING_DESTINATIONS["gyp"]
    got = dc._simple_folder_path(base, "Fuel House", "2026-07-10")
    assert got == base + "/26.07.10 Fuel House"
    assert "!" not in got            # no status marker
    assert "(" not in got            # no (Polish)/(Combo) suffix


def test_simple_folder_path_sanitizes_and_defaults_date():
    base = dc.ESTIMATING_DESTINATIONS["commercial"]
    leaf = dc._simple_folder_path(base, "A/B: C*?", None).rsplit("/", 1)[-1]
    assert re.match(r"^\d{2}\.\d{2}\.\d{2} ", leaf)          # missing date → today's YY.MM.DD
    for bad in ("/", "*", "?", ":"):
        assert bad not in leaf                               # illegal chars stripped


def test_upload_unconfigured_degrades_gracefully(monkeypatch):
    for k in ("DROPBOX_ACCESS_TOKEN", "DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    res = dc.upload_project_files(
        project_name="Test", xlsx_bytes=b"x", docx_bytes=b"d",
        base_path=dc.ESTIMATING_DESTINATIONS["gyp"], pdf_bytes=b"p",
    )
    assert res["configured"] is False
    assert "download" in res["error"].lower()


def test_bid_template_constants():
    assert dc.BID_TEMPLATE_PATH.endswith("/$$ Bid Template")
    assert dc.NUMBERS_SUBFOLDER.lower().startswith("numbers")
    assert "estimate sheet" in dc.TEMPLATE_ESTIMATE_NAME.lower()


def test_proposal_name_type_word_and_project_name():
    # MM.DD.YY + Treadwell TYPE word + the PROJECT NAME after the dash
    assert dc._project_proposal_name("Niagara Bottling", "epoxy", "2026-06-30", None) == \
        "06.30.26 TREADWELL EPOXY PROPOSAL - Niagara Bottling"
    assert dc._project_proposal_name("Maplewood Village", "gyp", "2025-11-21", None) == \
        "11.21.25 TREADWELL GYP UNDERLAYMENT PROPOSAL - Maplewood Village"
    assert "TREADWELL POLISH PROPOSAL" in dc._project_proposal_name("X", "polish", None, None)
    assert "TREADWELL COMBO PROPOSAL" in dc._project_proposal_name("X", "combo", None, None)
    # unknown/blank work type falls back to EPOXY
    assert "TREADWELL EPOXY PROPOSAL" in dc._project_proposal_name("X", "", "2026-01-02", None)


# ── /api/to-dropbox → dropbox_client.upload_project_files ────────────────────
# Written strict on purpose. The double HAS to take **kwargs to record the call,
# so it binds what it received against the real function — which has no **kwargs,
# making an undeclared keyword a TypeError in production that the route swallows
# into "Upload failed — please try again" for every filing.
GYP = dc.ESTIMATING_DESTINATIONS["gyp"]
COMMERCIAL = dc.ESTIMATING_DESTINATIONS["commercial"]

XLSX, DOCX, PDF = b"the-estimate-xlsx", b"the-proposal-docx", b"%PDF-1.4 the-proposal-pdf"


def _stub_route(monkeypatch, *, owner_subfolder=""):
    """Stub everything /api/to-dropbox needs except the upload, which records its
    kwargs into the returned dict."""
    captured: dict = {}
    data = {"proposal_payload": {
        "work_type": "polish", "audience": "GC",
        "values": {"project_name": "Trabon Group", "deadline": "2026-09-01",
                   "bid_date": "2026-08-14"}}}
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": data})
    monkeypatch.setattr(main.drafts, "save_draft", lambda i, d, **k: None)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main, "_generate", lambda gi, request, persist=True: main.GenerateOut(
        work_type=gi.work_type, audience=gi.audience, xlsx_download_url="/api/files/x",
        docx_download_url="/api/files/d", pdf_download_url="/api/files/d/pdf", totals={}))
    monkeypatch.setitem(main._FILE_CACHE, "x", {"content": XLSX})
    monkeypatch.setitem(main._FILE_CACHE, "d", {"content": DOCX, "_pdf": PDF})
    monkeypatch.setattr(main.dropbox_client, "destination_path",
                        lambda d: {"gyp": GYP, "commercial": COMMERCIAL}.get(d))
    monkeypatch.setattr(main.dropbox_client, "commercial_owner_subfolder",
                        lambda o: owner_subfolder)

    def fake_upload(**kw):
        assert_callable_accepts(_REAL_UPLOAD, kwargs=kw)
        captured.update(kw)
        return {"configured": True, "existing": False,
                "folder_path": kw["base_path"] + "/26.09.01 Trabon Group",
                "folder_url": "https://www.dropbox.com/x",
                "written_paths": [], "renamed": []}

    monkeypatch.setattr(main.dropbox_client, "upload_project_files", fake_upload)
    return captured


def test_the_route_hands_over_every_choice_the_estimator_made(monkeypatch):
    """The folder is NAMED from project_name + deadline and the proposal file from
    bid_date + work_type, so a dropped argument here files a correctly-generated
    proposal under a wrong name — or under today's date, which is half of the
    duplicate folders Kyle reported."""
    captured = _stub_route(monkeypatch)
    r = TestClient(main.app).post("/api/to-dropbox",
                                  json={"draft_id": "d1", "destination": "gyp"})
    assert r.status_code == 200, r.text
    assert captured["project_name"] == "Trabon Group"
    assert captured["deadline"] == "2026-09-01"
    assert captured["bid_date"] == "2026-08-14"
    assert captured["work_type"] == "polish"
    assert captured["audience"] == "GC"
    assert captured["base_path"] == GYP
    # Passed even when there is nothing to reuse — see test_dropbox_existing_folder
    # for the values themselves.
    assert "existing_folder_path" in captured and "known_paths" in captured


def test_the_estimate_and_proposal_bytes_are_not_crossed(monkeypatch):
    """Both files come out of the same cache dict two lines apart, and the names
    they get filed under are decided by which keyword they arrive in: crossing them
    puts the proposal inside "$ estimate sheet - <project>.xlsx" in Kyle's folder."""
    captured = _stub_route(monkeypatch)
    assert TestClient(main.app).post(
        "/api/to-dropbox", json={"draft_id": "d1", "destination": "gyp"}).status_code == 200
    assert captured["xlsx_bytes"] == XLSX
    assert captured["docx_bytes"] == DOCX
    assert captured["pdf_bytes"] == PDF      # the memoized render, not a re-render


def test_commercial_files_into_the_chosen_persons_subfolder(monkeypatch):
    """$Commercial Sales Estimates holds no project folders — only *Hanz *Kyle *RJ.
    Dropping the sub-folder join files the job one level too high, in the folder
    everyone shares."""
    captured = _stub_route(monkeypatch, owner_subfolder="*Kyle")
    r = TestClient(main.app).post("/api/to-dropbox", json={
        "draft_id": "d1", "destination": "commercial", "folder_owner": "kyle"})
    assert r.status_code == 200, r.text
    assert captured["base_path"] == COMMERCIAL + "/*Kyle"


def test_a_blank_owner_files_into_the_category_folder_itself(monkeypatch):
    """Hanz 2026-07-14: no person chosen → the category folder, not a *Name guess."""
    captured = _stub_route(monkeypatch, owner_subfolder="")
    r = TestClient(main.app).post("/api/to-dropbox",
                                  json={"draft_id": "d1", "destination": "commercial"})
    assert r.status_code == 200, r.text
    assert captured["base_path"] == COMMERCIAL


def test_dropbox_events_become_bell_notifications(monkeypatch):
    import notifications as n
    monkeypatch.setattr(n.drafts_mod, "list_events", lambda limit=100: [
        {"id": 9, "action": "to_dropbox", "project_id": "p1",
         "created_at": "2026-07-06T12:00:00+00:00",
         "detail": {"project_name": "Acme Plant", "label": "Gyp Estimates",
                    "folder_url": "https://www.dropbox.com/xyz"}},
        {"id": 8, "action": "created", "project_id": "p1", "created_at": "x", "detail": {}},
    ])
    items = n._dropbox_notifications()
    assert len(items) == 1                       # only the to_dropbox event
    it = items[0]
    assert it["kind"] == "to_dropbox" and it["icon"] == "📁"
    assert it["title"] == "Acme Plant"
    assert "Gyp Estimates" in it["body"]
    assert it["link"] == "https://www.dropbox.com/xyz"   # opens the Dropbox folder
    assert it["ts"] == "2026-07-06T12:00:00+00:00"       # drives unread
