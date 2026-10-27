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


def test_one_row_per_person_and_one_box_per_grant(ran):
    assert ran["rows"] == ["marisol@wetreadwell.com", "kyle@wetreadwell.com",
                           "boss@wetreadwell.com", "hanz@wetreadwell.com"]
    assert [h["label"] for h in ran["heads"]] == ["Items: price breaks", "Markup rules"]
    assert [h["title"] for h in ran["heads"]] == ["Edit price breaks.", "Edit markup rules."]
    assert len(ran["boxes"]) == 4 * 2


def test_member_boxes_follow_the_store_and_can_be_changed(ran):
    by = {(b["email"], b["key"]): b for b in ran["boxes"]}
    assert by[("marisol@wetreadwell.com", "items_pricing")] == {
        "email": "marisol@wetreadwell.com", "key": "items_pricing", "checked": True, "disabled": False}
    assert by[("marisol@wetreadwell.com", "markup")]["checked"] is False
    assert not any(by[("kyle@wetreadwell.com", k)]["checked"] for k in ("items_pricing", "markup"))
    assert not any(b["disabled"] for b in ran["boxes"] if b["email"].startswith(("marisol", "kyle")))


def test_admin_rows_are_all_ticked_and_disabled(ran):
    admins = [b for b in ran["boxes"] if b["email"] in ("boss@wetreadwell.com", "hanz@wetreadwell.com")]
    assert len(admins) == 4
    assert all(b["checked"] and b["disabled"] for b in admins)
    assert ran["adminNote"] == 2


def test_status_line_and_failed_load(ran):
    assert ran["status"]
    assert ran["failedSaysSo"]
