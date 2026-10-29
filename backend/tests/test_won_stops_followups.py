"""Marking a project Won, or handing it off, stops the automatic customer follow-up emails.

Hanz, 2026-10-28: "If staff mark a project Won (or Hand it off) by hand in the tool while the
portal still says sent/viewed, the automatic customer emails STOP."

The won mark and the hand-off live on OUR draft blob, which the portal never reads, so until this
the portal kept emailing a customer who had said yes on the phone. The route now also posts the
drawer's own per-project Follow-ups switch (`followup-automation`, enabled false) to the portal,
for THIS ONE proposal: the production build has one proposal per project and no scope groups.

Every test below executes the real `/api/draft/{id}/status` route, with drafts in the fake store
and a recording fake in place of `main._portal`. Each names the change it fails without.
"""
from fastapi import HTTPException
from fastapi.testclient import TestClient

import drafts
import main

client = TestClient(main.app)
ACTOR = "kyle@wetreadwell.com"


def _draft(did, data):
    return {"id": did, "data": data, "owner_email": "k@x.com", "created_at": "2026-10-0" + did[-1],
            "updated_at": "2026-10-10", "deleted_at": None}


class _Portal:
    """Records every call; `down` makes it unreachable, `missing` 404s those proposal ids."""

    def __init__(self, down=False, missing=()):
        self.calls, self.down, self.missing = [], down, set(missing)

    def __call__(self, path, method="GET", body=None):
        self.calls.append((path, method, body))
        if self.down:
            raise HTTPException(502, "Could not reach the customer portal.")
        for pid in self.missing:
            if "/proposal/%s/" % pid in path:
                raise HTTPException(404, "not_found")
        return {"ok": True}

    def switched(self):
        return [p.split("/")[4] for p, m, b in self.calls
                if p.endswith("/followup-automation") and m == "POST" and b == {"enabled": False,
                                                                               "by": ACTOR}]


def _wire(fake_supabase, monkeypatch, portal, sent=("solo", "twin")):
    """Two sent projects and an unsent one. `twin` shares solo's project name (and carries a stray
    scope-group key, as a copy made on staging could): it is a separate project all the same."""
    store = {"drafts": [_draft("solo", {"project_name": "Nearman Creek"}),
                        _draft("twin", {"project_name": "Nearman Creek",
                                        "scope_group": {"id": "grp-x", "label": "Lab 1"}}),
                        _draft("new", {"project_name": "Cedar Ridge"})],
             "draft_revisions": [{"project_id": pid, "revision_no": 1} for pid in sent],
             "events": []}
    fake = fake_supabase(store)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    monkeypatch.setattr(main, "_user_email", lambda request: ACTOR)
    monkeypatch.setattr(main, "_portal", portal)
    return store


def _data(store, did):
    return next(r for r in store["drafts"] if r["id"] == did)["data"]


def test_marking_a_sent_project_won_switches_its_follow_ups_off(fake_supabase, monkeypatch):
    """Mutation: remove the _followups_off_for_outcome call from the won branch; no POST is made."""
    portal = _Portal()
    store = _wire(fake_supabase, monkeypatch, portal)
    r = client.post("/api/draft/solo/status", json={"status": "won"})
    assert r.status_code == 200, r.text
    assert portal.switched() == ["solo"], portal.calls
    assert r.json()["followups_off"] == ["solo"]
    assert r.json()["followups_note"] == ""
    assert _data(store, "solo")["won"]["by"] == ACTOR


def test_handing_a_sent_project_off_switches_its_follow_ups_off(fake_supabase, monkeypatch):
    """Mutation: remove the call from the handed_off branch."""
    portal = _Portal()
    store = _wire(fake_supabase, monkeypatch, portal)
    r = client.post("/api/draft/solo/status", json={"status": "handed_off"})
    assert r.status_code == 200, r.text
    assert portal.switched() == ["solo"], portal.calls
    assert _data(store, "solo")["handed_off"]["by"] == ACTOR


def test_only_the_marked_proposal_is_switched_off(fake_supabase, monkeypatch):
    """ONE PROPOSAL, no scope-group expansion: production has no scope groups, so the mark on one
    draft switches that draft's emails off and no other project's, even one with the same name or
    a stray scope-group key. Mutation: look the project up by name, or expand a scope group (this
    build's drafts has no _group_rows, so the lookup raises and the mark reports a failure)."""
    portal = _Portal()
    _wire(fake_supabase, monkeypatch, portal)
    for did in ("twin", "solo"):
        portal.calls.clear()
        r = client.post("/api/draft/%s/status" % did, json={"status": "won"})
        assert r.status_code == 200, r.text
        assert portal.switched() == [did], portal.calls
        assert r.json()["followups_off"] == [did], r.json()
        assert r.json()["followups_failed"] == [] and r.json()["followups_note"] == ""


def test_an_unsent_project_is_asked_and_its_404_is_no_warning(fake_supabase, monkeypatch):
    """No portal row, so nothing to switch off and no warning either."""
    portal = _Portal(missing=["new"])
    _wire(fake_supabase, monkeypatch, portal)
    r = client.post("/api/draft/new/status", json={"status": "won"})
    assert r.status_code == 200, r.text
    assert r.json()["followups_off"] == [] and r.json()["followups_failed"] == []
    assert r.json()["followups_note"] == ""


def test_a_proposal_sent_before_revisions_existed_is_switched_off(fake_supabase, monkeypatch):
    """Review finding: a proposal published before #219 (2026-07-31) has a live portal row and no
    draft_revisions row. Treating "no revision" as "never sent" skipped it, answered an empty
    note, and the drawer said the emails had stopped while the portal kept sending them.
    Mutation: put back `if not drafts.latest_revision_no(pid): continue`; "solo" is never asked."""
    portal = _Portal()
    _wire(fake_supabase, monkeypatch, portal, sent=())          # NO revision rows at all
    r = client.post("/api/draft/solo/status", json={"status": "won"})
    assert r.status_code == 200, r.text
    assert portal.switched() == ["solo"], portal.calls
    assert r.json()["followups_off"] == ["solo"] and r.json()["followups_note"] == ""


def test_an_unreachable_portal_keeps_the_mark_and_says_so(fake_supabase, monkeypatch):
    """No silent failure. The mark saves, the answer is still ok, and the note names the problem.
    Asked once. "new" has no revision, but with the portal down that is not proof it was never
    sent (a pre-#219 send has none either), so it is counted too. Mutation: swallow the failure
    (empty followups_failed / no note), or let it raise (a 502 for a mark that saved)."""
    for did in ("solo", "new"):
        portal = _Portal(down=True)
        store = _wire(fake_supabase, monkeypatch, portal)
        r = client.post("/api/draft/%s/status" % did, json={"status": "won"})
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert "won" in _data(store, did), "the mark was lost because the portal was down"
        assert r.json()["followups_failed"] == [did], r.json()
        assert r.json()["followups_off"] == []
        note = r.json()["followups_note"]
        assert note.startswith("Saved as won, but"), note
        assert "could not be switched off" in note and "Turn automation off" in note, note
        assert "for this project" in note, note
        assert len(portal.calls) == 1, portal.calls


def test_no_portal_on_this_box_is_no_warning_for_a_proposal_never_sent(fake_supabase, monkeypatch):
    """503 is the portal being unconfigured here (_portal), so a proposal with no revision has no
    portal row anywhere to chase it (_portal_visibility's reading). One WITH a revision still is a
    failure: it was sent from somewhere. Counterexample for the unreachable test above."""
    def unconfigured(path, method="GET", body=None):
        raise HTTPException(503, "Customer portal isn't configured.")
    _wire(fake_supabase, monkeypatch, unconfigured)
    r = client.post("/api/draft/new/status", json={"status": "won"})
    assert r.status_code == 200, r.text
    assert r.json()["followups_failed"] == [] and r.json()["followups_note"] == "", r.json()
    r = client.post("/api/draft/solo/status", json={"status": "won"})     # solo was sent
    assert r.json()["followups_failed"] == ["solo"], r.json()


def test_an_unreachable_portal_on_a_hand_off_says_so_too(fake_supabase, monkeypatch):
    portal = _Portal(down=True)
    _wire(fake_supabase, monkeypatch, portal)
    r = client.post("/api/draft/solo/status", json={"status": "handed_off"})
    assert r.status_code == 200, r.text
    assert r.json()["followups_failed"] == ["solo"]
    assert r.json()["followups_note"].startswith("Saved as handed off, but"), r.json()
    assert "for this project" in r.json()["followups_note"]


def test_a_proposal_the_portal_no_longer_has_is_not_a_failure(fake_supabase, monkeypatch):
    """A 404 means nothing on the portal is chasing it, which is the outcome asked for."""
    portal = _Portal(missing=["solo"])
    _wire(fake_supabase, monkeypatch, portal)
    r = client.post("/api/draft/solo/status", json={"status": "won"})
    assert r.status_code == 200, r.text
    assert r.json()["followups_failed"] == [] and r.json()["followups_note"] == ""


def test_clearing_won_or_the_hand_off_does_not_turn_them_back_on(fake_supabase, monkeypatch):
    """Whether to chase the customer again is the Follow-up tab's switch, not an undo's side effect.
    Mutation: forward the clear to followup-automation (with either value)."""
    portal = _Portal()
    _wire(fake_supabase, monkeypatch, portal)
    for status in ("not_won", "not_handed_off"):
        r = client.post("/api/draft/solo/status", json={"status": status})
        assert r.status_code == 200, r.text
        assert "followups_off" not in r.json(), r.json()
    assert portal.calls == [], portal.calls


def test_bring_back_does_not_touch_the_follow_ups_switch(fake_supabase, monkeypatch):
    """bring_back forwards `active` to the portal's /status (unchanged); it never posts the switch,
    and the portal's `active` leaves followup_disabled_at alone (portal db.resume_followups)."""
    portal = _Portal()
    _wire(fake_supabase, monkeypatch, portal)
    r = client.post("/api/draft/solo/status", json={"status": "bring_back"})
    assert r.status_code == 200, r.text
    assert [p for p, _m, _b in portal.calls] == ["/api/admin/proposal/solo/status"], portal.calls


def test_a_mark_that_did_not_save_never_reaches_the_portal(fake_supabase, monkeypatch):
    """Draft first, portal second: a 502 for the mark must not have stopped the emails anyway.
    Mutation: switch the follow-ups off before set_won."""
    portal = _Portal()
    _wire(fake_supabase, monkeypatch, portal)

    def boom(*a):
        raise RuntimeError("postgrest down")
    monkeypatch.setattr(main.drafts, "set_won", boom)
    assert client.post("/api/draft/solo/status", json={"status": "won"}).status_code == 502
    assert portal.calls == []


def test_a_missing_project_never_reaches_the_portal(fake_supabase, monkeypatch):
    portal = _Portal()
    _wire(fake_supabase, monkeypatch, portal)
    assert client.post("/api/draft/gone/status", json={"status": "handed_off"}).status_code == 404
    assert portal.calls == []


# ── a proposal SENT AFTER the mark (review finding) ───────────────────────────
# The switch-off at the mark can only reach a proposal the portal already has. One sent later was
# enrolled by the portal's first publish (portal db.enroll_followup), and nothing read the draft's
# won / handed_off key, so the customer was chased about a job already won. These execute the real
# /api/portal/publish route over the same fake store.
EST = "kyle@wetreadwell.com"


def _wire_publish(fake_supabase, monkeypatch, portal, **kw):
    store = _wire(fake_supabase, monkeypatch, portal, **kw)
    monkeypatch.setattr(main.drafts, "create_revision", lambda did, data, by=None: 1)
    monkeypatch.setattr(main.drafts, "delete_revision", lambda did, no: None)
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(main.drafts, "set_assigned_estimator", lambda *a, **k: None)
    return store


def _publish(did):
    return client.post("/api/portal/publish?draft_id=" + did, json={"assigned_estimator": EST})


def _published(portal):
    return [b["draft_id"] for p, m, b in portal.calls if p == "/api/admin/publish"]


def test_sending_a_project_already_marked_won_switches_its_emails_off(fake_supabase, monkeypatch):
    """The customer says yes on the phone, the estimator marks the unsent project Won, then sends
    the formal proposal for signature. Mutation: drop the _followups_off_after_publish call from
    api_portal_publish; no switch-off follows the publish."""
    portal = _Portal(missing=["new"])
    _wire_publish(fake_supabase, monkeypatch, portal)
    assert client.post("/api/draft/new/status", json={"status": "won"}).status_code == 200
    portal.missing.clear()                       # the publish is what creates its portal row
    portal.calls.clear()
    r = _publish("new")
    assert r.status_code == 200, r.text
    paths = [p for p, _m, _b in portal.calls]
    assert paths == ["/api/admin/publish", "/api/admin/proposal/new/followup-automation"], paths
    assert portal.switched() == ["new"], portal.calls
    assert r.json()["followups_off"] == ["new"] and r.json()["followups_note"] == ""


def test_a_send_reads_only_its_own_draft_for_the_mark(fake_supabase, monkeypatch):
    """Another project marked won (with the same name, even) does not switch this one's emails off
    on send: the mark is read off the sent draft alone. Mutation: read the mark off any draft of
    the same project name, or off a scope group."""
    portal = _Portal()
    store = _wire_publish(fake_supabase, monkeypatch, portal)
    _data(store, "solo")["won"] = {"at": "2026-10-20T15:00:00Z", "by": ACTOR}
    r = _publish("twin")
    assert r.status_code == 200, r.text
    assert _published(portal) == ["twin"] and portal.switched() == [], portal.calls
    assert "followups_off" not in r.json(), r.json()


def test_sending_a_handed_off_project_switches_its_emails_off_too(fake_supabase, monkeypatch):
    portal = _Portal()
    store = _wire_publish(fake_supabase, monkeypatch, portal)
    _data(store, "new")["handed_off"] = {"at": "2026-10-20T15:00:00Z", "by": ACTOR}
    r = _publish("new")
    assert r.status_code == 200, r.text
    assert portal.switched() == ["new"], portal.calls


def test_an_ordinary_send_never_touches_the_follow_ups_switch(fake_supabase, monkeypatch):
    """The counterexample: nothing in the project is marked, so the cadence is left as the portal
    sets it, and the answer carries none of the switch-off keys."""
    portal = _Portal()
    _wire_publish(fake_supabase, monkeypatch, portal)
    for did in ("new", "twin"):
        r = _publish(did)
        assert r.status_code == 200, r.text
        assert "followups_off" not in r.json(), r.json()
    assert portal.switched() == [], portal.calls


def test_a_send_whose_switch_off_fails_is_still_sent_and_says_so(fake_supabase, monkeypatch):
    """The proposal has gone to the customer, so the send is a 200; the note says the emails are
    still on and what to press. Mutation: let the switch-off raise (a 502 for a send that went)."""
    calls = []

    def portal(path, method="GET", body=None):
        calls.append(path)
        if path.endswith("/followup-automation"):
            raise HTTPException(502, "Could not reach the customer portal.")
        return {"ok": True}
    store = _wire_publish(fake_supabase, monkeypatch, portal)
    _data(store, "new")["won"] = {"at": "2026-10-20T15:00:00Z", "by": ACTOR}
    r = _publish("new")
    assert r.status_code == 200, r.text
    assert calls == ["/api/admin/publish", "/api/admin/proposal/new/followup-automation"], calls
    assert r.json()["followups_failed"] == ["new"]
    note = r.json()["followups_note"]
    assert note.startswith("Sent.") and "marked won" in note and "Turn automation off" in note, note


# ── log safety (CodeQL, #739's last commit) ──────────────────────────────────
# The portal's refusal text and the draft id reach these log lines, and a newline in either would
# let whoever controls them forge a log line. Both switch-off paths log through main._log_safe.
FORGED = "boom\nINFO forged: follow-ups switched off"


def _warnings(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "proposal_tool"
            and "switch-off" in r.getMessage()]


def test_the_mark_s_switch_off_failure_logs_no_raw_newline(fake_supabase, monkeypatch, caplog):
    """Mutation: log exc.detail without _log_safe in _followups_off_for_outcome."""
    def refusing(path, method="GET", body=None):
        raise HTTPException(500, FORGED)
    _wire(fake_supabase, monkeypatch, refusing)
    caplog.set_level("WARNING", logger="proposal_tool")
    r = client.post("/api/draft/solo/status", json={"status": "won"})
    assert r.status_code == 200 and r.json()["followups_failed"] == ["solo"], r.text
    lines = _warnings(caplog)
    assert lines, "the failed switch-off was not logged"
    assert not [m for m in lines if "\n" in m], lines


def test_the_publish_s_switch_off_failure_logs_no_raw_newline(fake_supabase, monkeypatch, caplog):
    """Mutation: log the exception without _log_safe in _followups_off_after_publish."""
    def portal(path, method="GET", body=None):
        if path.endswith("/followup-automation"):
            raise HTTPException(500, FORGED)
        return {"ok": True}
    store = _wire_publish(fake_supabase, monkeypatch, portal)
    _data(store, "new")["won"] = {"at": "2026-10-20T15:00:00Z", "by": ACTOR}
    caplog.set_level("WARNING", logger="proposal_tool")
    r = _publish("new")
    assert r.status_code == 200 and r.json()["followups_failed"] == ["new"], r.text
    lines = _warnings(caplog)
    assert lines, "the failed switch-off was not logged"
    assert not [m for m in lines if "\n" in m], lines
