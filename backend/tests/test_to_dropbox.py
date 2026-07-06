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
    # Commercial Sales nests under the estimator sub-folder *Kyle (asterisk,
    # verified against the live Dropbox — NOT _Kyle).
    assert d["commercial"].endswith("/$Commercial Sales Estimates/*Kyle")
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
