"""The drawer's follow-up actions, and the estimator list that feeds the picker.

These are thin proxies to the portal, so what matters is that they validate before
forwarding: a bad `kind` or a bogus status must be rejected here rather than reaching
the portal and corrupting the digest's "has anyone chased this?" signal.
"""
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)
PID = "p1"


def _wire(monkeypatch, role="admin"):
    cap = {}
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": role})

    def fake_portal(path, method="GET", body=None):
        cap.update(path=path, method=method, body=body)
        return {"ok": True}

    monkeypatch.setattr(main, "_portal", fake_portal)
    return cap


# ── estimator list ───────────────────────────────────────────────────────────
def test_the_estimator_list_shows_active_people_only(monkeypatch):
    monkeypatch.setattr(main.profiles, "list_users", lambda: [
        {"email": "kyle@wetreadwell.com", "full_name": "Kyle Loseke", "status": "active"},
        {"email": "gone@wetreadwell.com", "full_name": "Gone", "status": "paused"},
        {"email": "troy@wetreadwell.com", "full_name": "Aaron Troy", "status": "active"},
    ])
    r = client.get("/api/estimators")
    assert r.status_code == 200
    got = r.json()["estimators"]
    assert [e["email"] for e in got] == ["troy@wetreadwell.com", "kyle@wetreadwell.com"]  # by name
    # Only what the picker renders — no roles, no ban details.
    assert set(got[0]) == {"email", "name"}


def test_a_profile_without_a_name_still_appears(monkeypatch):
    monkeypatch.setattr(main.profiles, "list_users",
                        lambda: [{"email": "new@wetreadwell.com", "status": "active"}])
    got = client.get("/api/estimators").json()["estimators"]
    assert got == [{"email": "new@wetreadwell.com", "name": "new@wetreadwell.com"}]


def test_the_files_page_still_loads_when_profiles_is_down(monkeypatch):
    """The picker will show "unavailable" and the send stays blocked — but the page
    must not break, and the send must not silently proceed unassigned."""
    def boom():
        raise RuntimeError("supabase down")

    monkeypatch.setattr(main.profiles, "list_users", boom)
    r = client.get("/api/estimators")
    assert r.status_code == 200 and r.json()["estimators"] == []


# ── reassign ─────────────────────────────────────────────────────────────────
def test_reassign_forwards_the_new_owner_and_who_did_it(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(f"/api/portal/proposal/{PID}/assign",
                    json={"estimator_email": "  Troy@WeTreadwell.com "})
    assert r.status_code == 200, r.text
    assert cap["path"] == f"/api/admin/proposal/{PID}/assign"
    assert cap["body"] == {"estimator_email": "troy@wetreadwell.com",
                           "by": "tester@wetreadwell.com"}


def test_reassign_rejects_a_bad_address(monkeypatch):
    cap = _wire(monkeypatch)
    assert client.post(f"/api/portal/proposal/{PID}/assign",
                       json={"estimator_email": "nope"}).status_code == 400
    assert cap == {}


# ── automation toggle ────────────────────────────────────────────────────────
def test_the_automation_toggle_forwards_a_real_boolean(monkeypatch):
    cap = _wire(monkeypatch)
    client.post(f"/api/portal/proposal/{PID}/followup-automation", json={"enabled": False})
    assert cap["body"]["enabled"] is False
    client.post(f"/api/portal/proposal/{PID}/followup-automation", json={"enabled": True})
    assert cap["body"]["enabled"] is True


# ── logging a follow-up ──────────────────────────────────────────────────────
def test_logging_a_call_forwards_kind_note_and_author(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(f"/api/portal/proposal/{PID}/followups",
                    json={"kind": "call", "note": "Left a voicemail"})
    assert r.status_code == 200, r.text
    assert cap["body"] == {"kind": "call", "note": "Left a voicemail",
                           "by": "tester@wetreadwell.com"}


def test_only_the_four_real_kinds_are_accepted(monkeypatch):
    """auto_email and customer_status are server-minted. Letting staff post them
    would corrupt the send dedupe and let a proposal look chased when it wasn't."""
    cap = _wire(monkeypatch)
    for bad in ("auto_email", "customer_status", "", "shout"):
        r = client.post(f"/api/portal/proposal/{PID}/followups", json={"kind": bad})
        assert r.status_code == 400, bad
    assert cap == {}


def test_a_long_note_is_capped(monkeypatch):
    cap = _wire(monkeypatch)
    client.post(f"/api/portal/proposal/{PID}/followups",
                json={"kind": "note", "note": "x" * 5000})
    assert len(cap["body"]["note"]) == 2000


def test_an_empty_note_forwards_as_nothing(monkeypatch):
    cap = _wire(monkeypatch)
    client.post(f"/api/portal/proposal/{PID}/followups", json={"kind": "text", "note": "   "})
    assert cap["body"]["note"] is None


# ── staff-set status ─────────────────────────────────────────────────────────
def test_marking_delayed_requires_one_of_the_offered_windows(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(f"/api/portal/proposal/{PID}/status",
                    json={"status": "delayed", "months": 2})
    assert r.status_code == 200 and cap["body"]["months"] == 2
    for bad in (0, 7, None):
        assert client.post(f"/api/portal/proposal/{PID}/status",
                           json={"status": "delayed", "months": bad}).status_code == 400


#: A comment good enough to get past the required field, and short enough to read in a failure.
NOTE = "We were 12% over Wilson on the pour."


def test_closed_lost_forwards_its_reason_and_its_comment(monkeypatch):
    """THE PROXY REBUILDS THE OUTBOUND BODY from a fixed key list, so a field added client-side is
    dropped without a word unless it is added here too — which is what makes this a test and not a
    formality. `note` joined the list on 2026-08-20 with the required comment."""
    cap = _wire(monkeypatch)
    r = client.post(f"/api/portal/proposal/{PID}/status",
                    json={"status": "closed_lost", "reason": "not_low_bid", "note": NOTE})
    assert r.status_code == 200, r.text
    assert cap["body"]["status"] == "closed_lost"
    assert cap["body"]["reason"] == "not_low_bid"
    assert cap["body"]["note"] == NOTE, (
        "the comment never left this process, so the estimator's sentence is lost: %r" % cap["body"])


def test_closing_a_sent_bid_is_refused_without_a_reason_or_a_comment(monkeypatch):
    """This proxy passed `reason` straight through until 2026-08-20 and the portal only checked it
    `if reason`, so a SENT project could be closed lost with no reason at all or with a made-up one
    — while the DRAFT route beside it 422s both. The Lost tab has no column for a reason nobody
    recognises, so that asymmetry filed dead bids under "Not recorded" from one drawer and never
    from the other. Both ends now refuse, and the whitespace cases are here because the required box
    is a textarea."""
    cap = _wire(monkeypatch)
    for body in ({"status": "closed_lost"},
                 {"status": "closed_lost", "note": NOTE},
                 {"status": "closed_lost", "reason": "vibes", "note": NOTE},
                 {"status": "closed_lost", "reason": "not_low_bid"},
                 {"status": "closed_lost", "reason": "not_low_bid", "note": "   "},
                 {"status": "closed_lost", "reason": "not_low_bid", "note": "\n\t"}):
        r = client.post(f"/api/portal/proposal/{PID}/status", json=body)
        assert r.status_code == 400, "%r got through" % body
    assert cap == {}, "one of those reached the portal: %r" % cap


def test_a_long_comment_is_capped_on_the_way_out(monkeypatch):
    cap = _wire(monkeypatch)
    client.post(f"/api/portal/proposal/{PID}/status",
                json={"status": "closed_lost", "reason": "to_rebid", "note": "x" * 5000})
    assert len(cap["body"]["note"]) == 2000


def test_a_hold_rides_the_delayed_status_with_its_reason_and_comment(monkeypatch):
    """Hanz, 2026-08-20: "Project on Hold" and "Small Bid <$25k - Pending" leave the card on the
    Active board with the reminders paused. On a project the customer HAS, that is the portal's
    existing `delayed` status — the one thing that pauses a cadence without moving the card — rather
    than a second pausing mechanism that would give one bid two pause dates able to disagree."""
    for reason in main.HOLD_REASONS:
        cap = _wire(monkeypatch)
        r = client.post(f"/api/portal/proposal/{PID}/status",
                        json={"status": "delayed", "months": 4, "reason": reason, "note": NOTE})
        assert r.status_code == 200, r.text
        assert cap["body"] == {"status": "delayed", "by": cap["body"]["by"], "months": 4,
                              "reason": reason, "note": NOTE}


def test_a_hold_is_refused_without_a_comment_or_with_a_lost_reason(monkeypatch):
    cap = _wire(monkeypatch)
    for body in ({"status": "delayed", "months": 4, "reason": "on_hold"},
                 {"status": "delayed", "months": 4, "reason": "on_hold", "note": "  "},
                 {"status": "delayed", "months": 4, "reason": "not_low_bid", "note": NOTE}):
        r = client.post(f"/api/portal/proposal/{PID}/status", json=body)
        assert r.status_code == 400, "%r got through" % body
    assert cap == {}


def test_the_bare_mark_delayed_control_still_needs_nothing(monkeypatch):
    """It predates the close-out dialog by three weeks: it picks a number of months and asks for no
    reason and no comment. Requiring one there would break the control this endpoint was built for
    in order to tidy up the one added on top of it."""
    cap = _wire(monkeypatch)
    r = client.post(f"/api/portal/proposal/{PID}/status", json={"status": "delayed", "months": 2})
    assert r.status_code == 200, r.text
    assert cap["body"]["months"] == 2
    assert "reason" not in cap["body"] and "note" not in cap["body"], (
        "an empty reason or comment is forwarded as a value, and the portal would file the pause "
        "as a hold nobody chose: %r" % cap["body"])


def test_an_unknown_status_never_reaches_the_portal(monkeypatch):
    cap = _wire(monkeypatch)
    assert client.post(f"/api/portal/proposal/{PID}/status",
                       json={"status": "won"}).status_code == 400
    assert cap == {}


def test_an_unsafe_proposal_id_is_refused(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/proposal/..%2Fevil/followups", json={"kind": "note"})
    assert r.status_code != 200
    assert cap == {}
