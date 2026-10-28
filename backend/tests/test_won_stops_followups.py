"""Marking a project Won, or handing it off, stops the automatic customer follow-up emails.

Hanz, 2026-10-28: "If staff mark a project Won (or Hand it off) by hand in the tool while the
portal still says sent/viewed, the automatic customer emails STOP."

The won mark and the hand-off live on OUR draft blob, which the portal never reads, so until this
the portal kept emailing a customer who had said yes on the phone. The route now also posts the
drawer's own per-project Follow-ups switch (`followup-automation`, enabled false) to the portal,
for every SENT proposal of the project's scope group.

Every test below executes the real `/api/draft/{id}/status` route, with drafts in the fake store
and a recording fake in place of `main._portal`. Each names the change it fails without.
"""
from fastapi import HTTPException
from fastapi.testclient import TestClient

import drafts
import main

client = TestClient(main.app)
ACTOR = "kyle@wetreadwell.com"
GID = "grp-acme"


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


def _wire(fake_supabase, monkeypatch, portal, sent=("solo", "g1", "g2")):
    """A sent ungrouped project, a three-scope project (g3 never sent), and an unsent project."""
    group = lambda label: {"project_name": "Acme HQ", "scope_group": {"id": GID, "label": label}}
    store = {"drafts": [_draft("solo", {"project_name": "Nearman Creek"}),
                        _draft("g1", group("Lab 1")), _draft("g2", group("Lab 2")),
                        _draft("g3", group("Breakroom")),
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


def test_every_sent_proposal_of_a_scope_group_is_switched_off(fake_supabase, monkeypatch):
    """The customer is chased with one email for the whole project, so a won mark on one scope
    stops all of them. g3 was never sent and has no portal row, so it is not asked.
    Mutation: drop the group expansion (only g1 switched), or the sent check (g3 asked and 404s)."""
    portal = _Portal()
    _wire(fake_supabase, monkeypatch, portal)
    r = client.post("/api/draft/g2/status", json={"status": "won"})
    assert r.status_code == 200, r.text
    assert sorted(portal.switched()) == ["g1", "g2"], portal.calls
    assert not any("/g3/" in p for p, _m, _b in portal.calls), "an unsent scope was asked"
    assert r.json()["followups_failed"] == []


def test_an_unsent_project_asks_the_portal_nothing(fake_supabase, monkeypatch):
    """No portal row, so nothing to switch off and no warning either."""
    portal = _Portal()
    _wire(fake_supabase, monkeypatch, portal)
    r = client.post("/api/draft/new/status", json={"status": "won"})
    assert r.status_code == 200, r.text
    assert portal.calls == []
    assert r.json()["followups_note"] == ""


def test_an_unreachable_portal_keeps_the_mark_and_says_so(fake_supabase, monkeypatch):
    """No silent failure. The mark saves, the answer is still ok, and the note names the problem.
    The portal is asked ONCE for the group, not once per scope (twelve 20s timeouts would hang the
    drawer for minutes). Mutation: swallow the failure (empty followups_failed / no note), or let
    it raise (a 502 for a mark that saved)."""
    portal = _Portal(down=True)
    store = _wire(fake_supabase, monkeypatch, portal)
    r = client.post("/api/draft/g1/status", json={"status": "won"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    assert "won" in _data(store, "g1"), "the mark was lost because the portal was down"
    assert sorted(r.json()["followups_failed"]) == ["g1", "g2"], r.json()
    assert r.json()["followups_off"] == []
    note = r.json()["followups_note"]
    assert "could not be switched off" in note and "Turn automation off" in note, note
    assert "2 of the proposals" in note, note
    assert len(portal.calls) == 1, "the unreachable portal was asked again for every scope"


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
