"""The Admin page's Special permissions card, rendered by admin.js's own grantsPanelHtml."""
import json
import pathlib
import shutil
import subprocess

import pytest

HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "special-permissions-harness.js"
FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(["node", str(HARNESS), str(FRONTEND)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_one_row_per_person_and_one_box_per_tab(ran):
    assert ran["rows"] == ["marisol@wetreadwell.com", "kyle@wetreadwell.com",
                           "boss@wetreadwell.com", "hanz@wetreadwell.com"]
    # The tab's label as the header, its path as the title.
    assert [h["label"] for h in ran["heads"]] == ["Items and Assemblies", "Markup"]
    assert [h["title"] for h in ran["heads"]] == ["/library.html", "/markup.html"]
    assert len(ran["boxes"]) == 4 * 2


def test_the_card_says_what_a_tick_gives_and_scrolls_sideways(ran):
    assert ran["tabNote"]
    assert ran["scrolls"]


def test_the_columns_the_server_serves_are_every_tab_but_admin(monkeypatch):
    """The card draws one column per catalog entry, and the catalog is TABS minus the Admin page."""
    import main
    import nav_access
    from fastapi.testclient import TestClient
    monkeypatch.setattr(main, "_user_email", lambda request: "boss@wetreadwell.com")
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {
        "id": "u1", "email": "boss@wetreadwell.com", "role": "admin", "status": "active"})
    main._profile_cache_clear()
    body = TestClient(main.app).get("/api/admin/special-permissions").json()
    main._profile_cache_clear()
    assert [(g["key"], g["label"]) for g in body["grants_catalog"]] == [
        (h, t["label"]) for h, t in nav_access.TABS.items() if h != "/admin.html"]


def test_member_boxes_follow_the_store_and_can_be_changed(ran):
    by = {(b["email"], b["key"]): b for b in ran["boxes"]}
    assert by[("marisol@wetreadwell.com", "/library.html")] == {
        "email": "marisol@wetreadwell.com", "key": "/library.html", "checked": True, "disabled": False}
    assert by[("marisol@wetreadwell.com", "/markup.html")]["checked"] is False
    assert not any(by[("kyle@wetreadwell.com", k)]["checked"] for k in ("/library.html", "/markup.html"))
    assert not any(b["disabled"] for b in ran["boxes"] if b["email"].startswith(("marisol", "kyle")))


def test_admin_rows_are_all_ticked_and_disabled(ran):
    admins = [b for b in ran["boxes"] if b["email"] in ("boss@wetreadwell.com", "hanz@wetreadwell.com")]
    assert len(admins) == 4
    assert all(b["checked"] and b["disabled"] for b in admins)
    assert ran["adminNote"] == 2


def test_status_line_and_failed_load(ran):
    assert ran["status"]
    assert ran["failedSaysSo"]


def test_a_second_tick_cannot_land_while_a_save_is_in_flight(ran):
    # Each save PUTs the whole map from the last saved copy: a second tick sent mid-save would
    # leave the first one out, so every box stays disabled until the answer redraws the card.
    assert ran["inFlight"]["puts"] == 1
    assert ran["inFlight"]["allDisabled"]
