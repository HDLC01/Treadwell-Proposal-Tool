"""/api/portal/publish proxy — the optional multi-recipient body.

The endpoint forwards to the external portal's /api/admin/publish. These tests
monkeypatch main._portal to capture exactly what gets forwarded, and
main.drafts.load_draft so the existence check passes without a DB. The conftest
autouse fixture authenticates every request as tester@wetreadwell.com."""
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)

URL = "/api/portal/publish?draft_id=d1"
# Publishing now requires an owner for the follow-up cadence.
EST = "kyle@wetreadwell.com"


def _wire(monkeypatch, role="admin"):
    captured = {}
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": {}})
    # _require_admin / _caller_is_admin resolve the caller's role via profiles;
    # stub it so the admin-gated notify endpoints don't hit Supabase in CI.
    monkeypatch.setattr(main.profiles, "get_by_email", lambda e: {"email": e, "role": role})
    # Every publish snapshots the draft as a revision (the portal pins the customer
    # view to it). Recorded LAZILY — several tests assert `cap == {}` to mean "the
    # request never reached the portal", so pre-seeding keys here would break them.
    monkeypatch.setattr(main.drafts, "create_revision",
                        lambda did, data, by=None:
                        captured.setdefault("revisions", []).append((did, by)) or 1)
    monkeypatch.setattr(main.drafts, "delete_revision",
                        lambda did, no: captured.setdefault("deleted", []).append((did, no)))
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)

    def fake_portal(path, method="GET", body=None):
        captured.update(path=path, method=method, body=body)
        return {"ok": True, "url": "https://portal/x", "customer_email": "c@x.com",
                "recipients": (body or {}).get("emails") or ["c@x.com"]}

    monkeypatch.setattr(main, "_portal", fake_portal)
    return captured


def test_no_body_sends_only_the_essentials(monkeypatch):
    """A body-less call must still forward nothing optional — no emails key, no
    require_deposit — so the portal's own defaults apply. `revision_no` is not
    optional: every send snapshots what it sent, which is what the customer's view
    is then pinned to."""
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"assigned_estimator": EST})
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/publish" and cap["method"] == "POST"
    assert cap["body"] == {"draft_id": "d1", "by": "tester@wetreadwell.com",
                       "assigned_estimator": EST, "revision_no": 1}


def test_snapshot_is_taken_before_the_portal_call(monkeypatch):
    cap = _wire(monkeypatch)
    assert client.post(URL, json={"assigned_estimator": EST}).status_code == 200
    assert cap.get("revisions") == [("d1", "tester@wetreadwell.com")]
    assert cap["body"]["revision_no"] == 1
    assert cap.get("deleted", []) == []


def test_snapshot_is_rolled_back_when_the_send_fails(monkeypatch):
    """A snapshot represents a version the customer RECEIVED. If the portal call
    fails, nothing was received, so the revision must not survive and misreport the
    history to staff."""
    cap = _wire(monkeypatch)

    def boom(path, method="GET", body=None):
        raise main.HTTPException(502, "portal down")

    monkeypatch.setattr(main, "_portal", boom)
    r = client.post(URL, json={"assigned_estimator": EST})
    assert r.status_code == 502
    assert cap.get("revisions") == [("d1", "tester@wetreadwell.com")]
    assert cap.get("deleted") == [("d1", 1)]


def test_no_snapshot_when_validation_rejects_the_request(monkeypatch):
    """A 400 must not mint a revision — otherwise a typo in an email address would
    leave a phantom "sent" version in the project's history."""
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": ["not-an-email"]})
    assert r.status_code == 400
    assert cap.get("revisions", []) == [] and cap.get("deleted", []) == []


def test_publishing_without_an_owner_is_refused(monkeypatch):
    """Hanz: always explicit. An unassigned proposal is one nobody chases — no
    reminder notes, no digest entry — which is the exact failure the follow-up system
    exists to fix. Critically it must fail BEFORE the snapshot, or a rejected send
    would leave a phantom "sent" version in the project's history."""
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": ["a@x.com"]})
    assert r.status_code == 400 and "missing_estimator" in r.text
    assert cap.get("revisions", []) == []
    assert "path" not in cap                       # the portal was never called


def test_a_malformed_estimator_address_is_refused(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"assigned_estimator": "not-an-email"})
    assert r.status_code == 400 and "invalid_estimator" in r.text
    assert cap.get("revisions", []) == []


def test_the_owner_is_normalised_and_forwarded(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"assigned_estimator": "  KYLE@WeTreadwell.com  "})
    assert r.status_code == 200, r.text
    assert cap["body"]["assigned_estimator"] == "kyle@wetreadwell.com"


def test_recipient_errors_still_win_over_the_owner_check(monkeypatch):
    """Both are missing here. The recipient message is the more specific and the
    older contract, so it is the one the estimator should see."""
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": ["not-an-email"]})
    assert r.status_code == 400 and "invalid_email" in r.text


def test_forwards_require_deposit_both_ways(monkeypatch):
    """The Files-page checkbox. False is the interesting one — it must survive as an
    explicit False rather than being dropped as falsy, or a GC job would silently
    get a deposit invoice on approval."""
    cap = _wire(monkeypatch)
    assert client.post(URL, json={"require_deposit": True, "assigned_estimator": EST}).status_code == 200
    assert cap["body"]["require_deposit"] is True
    cap2 = _wire(monkeypatch)
    assert client.post(URL, json={"require_deposit": False, "assigned_estimator": EST}).status_code == 200
    assert cap2["body"]["require_deposit"] is False


def test_require_deposit_omitted_when_not_specified(monkeypatch):
    """A body without the field must not send one: the portal reads a missing field
    as "keep what you have", so a re-send from an older page can't flip a job that
    was deliberately sent without a deposit."""
    cap = _wire(monkeypatch)
    assert client.post(URL, json={"emails": ["a@x.com"], "assigned_estimator": EST}).status_code == 200
    assert "require_deposit" not in cap["body"]


def test_forwards_valid_emails(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": [" A@x.com ", "b@y.co"], "assigned_estimator": EST})
    assert r.status_code == 200, r.text
    assert cap["body"]["emails"] == ["A@x.com", "b@y.co"]        # trimmed, casing preserved
    assert cap["body"]["draft_id"] == "d1"


def test_dedupes_case_insensitively(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": ["a@x.com", "A@X.COM", "b@y.co"], "assigned_estimator": EST})
    assert r.status_code == 200
    assert cap["body"]["emails"] == ["a@x.com", "b@y.co"]


def test_empty_or_blank_list_is_legacy(monkeypatch):
    cap = _wire(monkeypatch)
    assert client.post(URL, json={"emails": [], "assigned_estimator": EST}).status_code == 200
    assert "emails" not in cap["body"]
    assert client.post(URL, json={"emails": ["", "  "], "assigned_estimator": EST}).status_code == 200
    assert "emails" not in cap["body"]


def test_rejects_invalid_email(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": ["not-an-email"]})
    assert r.status_code == 400 and "invalid_email" in r.text
    assert cap == {}                                            # _portal never called


def test_caps_at_ten(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post(URL, json={"emails": [f"u{i}@x.com" for i in range(11)]})
    assert r.status_code == 400 and "too_many_emails" in r.text
    assert cap == {}


def test_garbage_body_never_500s(monkeypatch):
    _wire(monkeypatch)
    r = client.post(URL, content=b"{{{", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    r = client.post(URL, json={"emails": "a@x.com"})           # string, not list
    assert r.status_code == 422


def test_404_when_draft_missing(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: None)
    assert client.post(URL, json={"emails": ["a@x.com"], "assigned_estimator": EST}).status_code == 404


def test_rejects_unsafe_draft_id(monkeypatch):
    _wire(monkeypatch)
    r = client.post("/api/portal/publish?draft_id=..%2Fevil", json={"emails": ["a@x.com"]})
    assert r.status_code == 400


# ── deposit-request proxy (staff-triggered) ───────────────────────────────────
def test_deposit_request_no_body_omits_amount(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/proposal/p1/deposit-request")
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/proposal/p1/deposit-request" and cap["method"] == "POST"
    assert cap["body"] == {"by": "tester@wetreadwell.com"}     # no amount key when none sent


def test_deposit_request_forwards_amount_override(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/proposal/p1/deposit-request", json={"amount": 1500})
    assert r.status_code == 200, r.text
    assert cap["body"]["amount"] == 1500 and cap["body"]["by"] == "tester@wetreadwell.com"


def test_deposit_request_null_amount_omitted(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/proposal/p1/deposit-request", json={"amount": None})
    assert r.status_code == 200, r.text
    assert "amount" not in cap["body"]


# ── notify-recipients proxy ───────────────────────────────────────────────────
def test_notify_list_proxies(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.get("/api/portal/notify-recipients")
    assert r.status_code == 200
    assert cap["path"] == "/api/admin/notify-recipients" and cap["method"] == "GET"


def test_notify_add_forwards_cleaned(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/notify-recipients", json={"email": " Kyle@X.com ", "kind": "deposit"})
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/notify-recipients" and cap["method"] == "POST"
    assert cap["body"] == {"email": "kyle@x.com", "kind": "deposit", "by": "tester@wetreadwell.com"}


def test_notify_add_defaults_kind_general(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/notify-recipients", json={"email": "a@x.com"})
    assert r.status_code == 200
    assert cap["body"]["kind"] == "general"


def test_notify_add_rejects_bad_email(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/notify-recipients", json={"email": "nope", "kind": "general"})
    assert r.status_code == 400
    assert cap == {}                                             # _portal never called


def test_notify_add_rejects_bad_kind(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.post("/api/portal/notify-recipients", json={"email": "a@x.com", "kind": "boss"})
    assert r.status_code == 400
    assert cap == {}


def test_notify_delete_proxies(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.delete("/api/portal/notify-recipients/7")
    assert r.status_code == 200
    assert cap["path"] == "/api/admin/notify-recipients/7" and cap["method"] == "DELETE"


def test_notify_add_requires_admin(monkeypatch):
    _wire(monkeypatch, role="user")                              # non-admin caller
    r = client.post("/api/portal/notify-recipients", json={"email": "a@x.com"})
    assert r.status_code == 403


def test_notify_toggle_proxies(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.patch("/api/portal/notify-recipients/5", json={"enabled": False})
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/notify-recipients/5" and cap["method"] == "PATCH"
    assert cap["body"] == {"enabled": False}


# ── per-project notify overrides proxy ────────────────────────────────────────
def test_overrides_get_proxies(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.get("/api/portal/proposal/p1/notify-overrides")
    assert r.status_code == 200
    assert cap["path"] == "/api/admin/proposal/p1/notify-overrides" and cap["method"] == "GET"


def test_overrides_all_proxies(monkeypatch):
    cap = _wire(monkeypatch)                                     # read-only, not admin-gated
    r = client.get("/api/portal/notify-overrides-all")
    assert r.status_code == 200
    assert cap["path"] == "/api/admin/notify-overrides" and cap["method"] == "GET"


def test_overrides_put_admin_forwards(monkeypatch):
    cap = _wire(monkeypatch)                                     # admin
    r = client.put("/api/portal/proposal/p1/notify-overrides", json={"email": "Dane@X.com", "mode": "add"})
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/proposal/p1/notify-overrides" and cap["method"] == "PUT"
    assert cap["body"] == {"email": "dane@x.com", "mode": "add"}


def test_overrides_put_nonadmin_self_ok(monkeypatch):
    cap = _wire(monkeypatch, role="user")                        # non-admin toggling THEMSELVES
    r = client.put("/api/portal/proposal/p1/notify-overrides",
                   json={"email": "tester@wetreadwell.com", "mode": "mute"})
    assert r.status_code == 200, r.text
    assert cap["body"] == {"email": "tester@wetreadwell.com", "mode": "mute"}


def test_overrides_put_nonadmin_other_forbidden(monkeypatch):
    cap = _wire(monkeypatch, role="user")                        # non-admin toggling SOMEONE ELSE
    r = client.put("/api/portal/proposal/p1/notify-overrides", json={"email": "dane@x.com", "mode": "add"})
    assert r.status_code == 403
    assert cap == {}                                             # _portal never called


def test_overrides_put_rejects_bad_mode(monkeypatch):
    cap = _wire(monkeypatch)
    r = client.put("/api/portal/proposal/p1/notify-overrides", json={"email": "a@x.com", "mode": "boss"})
    assert r.status_code == 400
    assert cap == {}


# ── who BUILT the estimate rides along ────────────────────────────────────────
# Will, via Hanz on 2026-08-13: "There are set members for the global notification. And this
# estimator or treadwell employee created an estimate, by default this estimator should be
# included." The portal turns this into one of the project's notification recipients.
#
# Three different people can be in one send and they are not interchangeable: `by` is whoever
# pressed Send, `assigned_estimator` is who owns chasing it, and `created_by` is whose estimate
# it is. RJ can price a bid and hand it to Kyle.
def test_the_drafts_owner_is_forwarded_as_the_creator(monkeypatch):
    cap = _wire(monkeypatch)
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda i: {"id": i, "data": {}, "owner_email": "rj@wetreadwell.com"})
    r = client.post(URL, json={"assigned_estimator": EST})
    assert r.status_code == 200, r.text
    assert cap["body"]["created_by"] == "rj@wetreadwell.com"


def test_the_creator_comes_from_the_STORED_owner_not_the_caller(monkeypatch):
    """The person pressing Send is usually somebody else, and a browser must not be able to claim
    authorship of an estimate — that would put whoever it named on the project's notifications."""
    cap = _wire(monkeypatch)
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda i: {"id": i, "data": {}, "owner_email": "rj@wetreadwell.com"})
    r = client.post(URL, json={"assigned_estimator": EST, "created_by": "someone@else.com"})
    assert r.status_code == 200, r.text
    assert cap["body"]["created_by"] == "rj@wetreadwell.com"
    # And the field cannot be reached at all: the body model has no `created_by`, so a caller
    # supplying one is not merely overridden, it is never parsed.
    assert "created_by" not in main.PortalPublishIn.model_fields


def test_an_ownerless_draft_claims_nothing(monkeypatch):
    """Drafts created before owners were stamped have none. The send must look exactly as it did
    before this existed — an empty `created_by` would be a roster row for nobody."""
    cap = _wire(monkeypatch)
    monkeypatch.setattr(main.drafts, "load_draft", lambda i: {"id": i, "data": {}})
    r = client.post(URL, json={"assigned_estimator": EST})
    assert r.status_code == 200, r.text
    assert "created_by" not in cap["body"], cap["body"]
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda i: {"id": i, "data": {}, "owner_email": "   "})
    client.post(URL, json={"assigned_estimator": EST})
    assert "created_by" not in cap["body"], cap["body"]


def test_the_creator_is_forwarded_on_a_resend_too(monkeypatch):
    """Every publish carries it, so projects that predate this pick it up on their next send."""
    cap = _wire(monkeypatch)
    monkeypatch.setattr(main.drafts, "load_draft",
                        lambda i: {"id": i, "data": {}, "owner_email": "rj@wetreadwell.com"})
    monkeypatch.setattr(main.drafts, "create_revision", lambda did, data, by=None: 4)
    r = client.post(URL, json={"assigned_estimator": EST, "emails": ["a@x.com"]})
    assert r.status_code == 200, r.text
    assert cap["body"]["created_by"] == "rj@wetreadwell.com"
    assert cap["body"]["revision_no"] == 4


# ── the per-step cell proxy ──────────────────────────────────────────────────
# PUT /api/portal/notify-recipients/step is how the Notification Sending page's matrix writes one
# (person, step) cell. It exists as its own route rather than reusing the POST-then-PATCH pair the
# chips use, because that pair creates the row disabled and then enables it: a half-failed click
# would leave a cell reading off that nobody chose, and it would have to fight the roster cap on
# the way in.
STEP_URL = "/api/portal/notify-recipients/step"


def test_notify_step_forwards_cleaned(monkeypatch):
    """Address and step normalised, and the caller recorded. `by` is what the portal stores as
    added_by, so "who turned this on" survives."""
    cap = _wire(monkeypatch)
    r = client.put(STEP_URL, json={"email": " Kyle@X.com ", "step": " VIEWED ", "state": "Off"})
    assert r.status_code == 200, r.text
    assert cap["path"] == "/api/admin/notify-recipients/step" and cap["method"] == "PUT"
    assert cap["body"] == {"email": "kyle@x.com", "step": "viewed", "state": "off",
                           "by": "tester@wetreadwell.com"}


def test_notify_step_accepts_the_three_states_and_nothing_else(monkeypatch):
    """Three, because a cell has three meanings: an explicit on, an explicit off, and no row at
    all. Collapsing them to a boolean would make an off cell indistinguishable from an untouched
    one, and the two resolve differently.

    Mutation: drop the state check and "maybe" is forwarded to the portal."""
    for state in ("on", "off", "inherit"):
        cap = _wire(monkeypatch)
        assert client.put(STEP_URL, json={"email": "a@x.com", "step": "sent",
                                          "state": state}).status_code == 200
        assert cap["body"]["state"] == state
    for state in ("maybe", "", "true", "1", "clear"):
        cap = _wire(monkeypatch)
        assert client.put(STEP_URL, json={"email": "a@x.com", "step": "sent",
                                          "state": state}).status_code == 400, state
        assert cap == {}, state


def test_notify_step_checks_the_shape_of_the_step_but_not_its_meaning(monkeypatch):
    """The PORTAL owns the vocabulary (email_sender.NOTIFY_STEPS) and validates it on the way in.
    A second copy of the list here is a copy that drifts, and the drift would be silent: this tool
    would refuse a step the portal had just learned. So the shape is checked and the meaning is
    not."""
    cap = _wire(monkeypatch)
    # A step this tool has never heard of still goes through, because it might be real tomorrow.
    assert client.put(STEP_URL, json={"email": "a@x.com", "step": "invoice_issued",
                                      "state": "on"}).status_code == 200
    assert cap["body"]["step"] == "invoice_issued"
    for step in ("", "Sent!", "a" * 33, "step-name", "step2", "_sent"):
        cap = _wire(monkeypatch)
        assert client.put(STEP_URL, json={"email": "a@x.com", "step": step,
                                          "state": "on"}).status_code == 400, step
        assert cap == {}, step


def test_notify_step_rejects_a_bad_address(monkeypatch):
    cap = _wire(monkeypatch)
    assert client.put(STEP_URL, json={"email": "nope", "step": "sent",
                                      "state": "on"}).status_code == 400
    assert cap == {}


def test_notify_step_is_admin_only(monkeypatch):
    """Unlike the per-project chips, where anybody may silence their own address on one job. This
    is the org-wide roster: one estimator quietly taking the team off "proposal approved" is the
    sort of change nobody notices until a deal goes cold.

    Mutation: drop the _require_admin call and this returns 200."""
    cap = _wire(monkeypatch, role="estimator")
    r = client.put(STEP_URL, json={"email": "tester@wetreadwell.com", "step": "sent",
                                  "state": "off"})
    assert r.status_code in (401, 403), r.text
    assert cap == {}, "a non-admin write reached the portal"
