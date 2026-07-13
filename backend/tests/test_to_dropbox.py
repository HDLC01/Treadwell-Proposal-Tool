"""Step-5 'To Dropbox': destination map + the simple YY.MM.DD folder convention.

These cover the NEW behavior only; the existing folder/filename conventions are
pinned by test_dropbox_naming.py and the graceful-degradation contract by
test_security_misc.py (both left untouched)."""
import re

import dropbox_client as dc


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
