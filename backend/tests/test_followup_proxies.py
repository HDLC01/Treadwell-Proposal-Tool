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


def test_closed_lost_forwards_its_reason(monkeypatch):
    cap = _wire(monkeypatch)
    client.post(f"/api/portal/proposal/{PID}/status",
                json={"status": "closed_lost", "reason": "price"})
    assert cap["body"]["status"] == "closed_lost" and cap["body"]["reason"] == "price"


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
