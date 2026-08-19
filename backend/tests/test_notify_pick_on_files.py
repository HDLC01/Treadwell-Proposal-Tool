"""Choosing who on the team hears about a send, on the Files screen.

Hanz, 2026-08-19: "we need that notifcation sending selection in the Files. so we can select who
receives it first."

WHY THE PICKS TRAVEL IN THE PUBLISH BODY, which is the whole design and the reason this file exists.

`portal_notify_overrides.proposal_id` is a foreign key onto `portal_proposals`. On a FIRST send that
row does not exist until `admin_publish` creates it, so the obvious client-side sequence — PUT the
overrides, then publish — is refused by the portal's 404 guard and by the FK underneath it. It would
appear to work on every re-send and fail on the one send that matters most, silently, because the
staff notification would simply resolve against the unmodified roster.

So the deviations ride along with the publish, and the portal applies them after it creates the row
and before it resolves who to notify. These tests pin that they are forwarded, cleaned, and omitted
when nothing was changed — the last one matters because an always-sent field would change the legacy
request body for every caller that never touches the control.
"""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)

URL = "/api/portal/publish?draft_id=d1"
EST = "kyle@wetreadwell.com"


@pytest.fixture
def wire(monkeypatch):
    """A publish that reaches no portal and no database, recording the forwarded body."""
    sent = {}

    def fake_portal(path, method="GET", body=None):
        sent["path"], sent["body"] = path, body
        return {"ok": True, "token": "t", "url": "u"}

    monkeypatch.setattr(main, "_portal", fake_portal)
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda pid: {"data": {}, "owner_email": "rj@wetreadwell.com"})
    monkeypatch.setattr(main.drafts, "create_revision", lambda *a, **k: 1)
    monkeypatch.setattr(main.drafts, "delete_revision", lambda *a, **k: None)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: None)
    # An ADMIN, because these tests are about the picks being forwarded and cleaned, and since
    # 2026-08-19 this route also checks that the caller is allowed to make the change it forwards.
    # Kyle and Hanz are admins, so this is the ordinary case; the permission rule itself is covered
    # in test_notify_picks_permission.py, including on this route.
    monkeypatch.setattr(main, "_caller_is_admin", lambda request: True)
    return sent


def test_the_chosen_names_are_forwarded(wire):
    r = client.post(URL, json={"assigned_estimator": EST,
                               "notify_add": ["will@wetreadwell.com"],
                               "notify_mute": ["troy@wetreadwell.com"]})
    assert r.status_code == 200, r.text
    assert wire["body"]["notify_add"] == ["will@wetreadwell.com"]
    assert wire["body"]["notify_mute"] == ["troy@wetreadwell.com"]


def test_nothing_is_forwarded_when_nothing_was_changed(wire):
    """An untouched control must leave the request byte-for-byte what it always was. A field sent
    as an empty list would still be a new field in the body, and `admin_publish` would then run its
    reconcile — including the clear-the-rest pass — on every send from every older page."""
    r = client.post(URL, json={"assigned_estimator": EST})
    assert r.status_code == 200
    assert "notify_add" not in wire["body"] and "notify_mute" not in wire["body"]
    assert set(wire["body"]) == {"draft_id", "by", "created_by", "assigned_estimator",
                                 "revision_no"}


def test_a_malformed_address_is_refused_rather_than_dropped(wire):
    """Same helper as `emails` and `no_followups`. Dropping a bad entry silently would mean
    somebody clicked a name, saw it go green, and was never told."""
    r = client.post(URL, json={"assigned_estimator": EST, "notify_add": ["not-an-email"]})
    assert r.status_code == 400, r.text


def test_one_name_clicked_twice_is_one_name(wire):
    """Deduped case-insensitively by the same helper the customer addresses use, which keeps the
    first casing on purpose — a customer's address is displayed as they typed it. Casing does not
    matter here because the portal lowercases every notify address before it stores one, but the
    duplicate does: two rows for one person is two upserts and a confusing roster."""
    r = client.post(URL, json={"assigned_estimator": EST,
                               "notify_add": [" Will@Wetreadwell.com ", "will@wetreadwell.com"]})
    assert r.status_code == 200, r.text
    assert wire["body"]["notify_add"] == ["Will@Wetreadwell.com"]
