"""Who can be assigned a proposal — the estimator roster.

`/api/estimators` used to return every active profile, so the picker listed everyone who
had ever signed in, estimator or not. `profiles.is_estimator` curates it.

Hanz's constraint shapes the design: "Treadwell employees could both be members, admins
and estimators at the same time." So this is a FLAG, independent of `role` — a
single-valued role column cannot express it.

The test that matters most is the fallback. Publishing REFUSES to send without an
estimator, so an empty picker doesn't degrade the app, it stops the business. Before
anyone has ticked a box the roster has to behave exactly as it did yesterday.
"""
from fastapi.testclient import TestClient

import main
import profiles

client = TestClient(main.app)


def _users(monkeypatch, rows):
    monkeypatch.setattr(profiles, "list_users", lambda *a, **k: rows)


def u(email, *, estimator=False, status="active", role="user", name=None, banned=None):
    return {"id": email.split("@")[0], "email": email, "full_name": name,
            "role": role, "status": status, "is_estimator": estimator,
            "banned_at": banned}


# ── the roster ──────────────────────────────────────────────────────────────
def test_only_the_flagged_people_are_assignable(monkeypatch):
    _users(monkeypatch, [u("kyle@wetreadwell.com", estimator=True),
                         u("will@wetreadwell.com"),
                         u("troy@wetreadwell.com", estimator=True)])
    got = [x["email"] for x in profiles.list_estimators()]
    assert got == ["kyle@wetreadwell.com", "troy@wetreadwell.com"]


def test_nobody_flagged_yet_falls_back_to_everyone_active(monkeypatch):
    """THE load-bearing case. Publishing 400s without an estimator, so an empty picker on
    the morning of the deploy would block every send in the building. The roster behaves
    exactly as it did before the flag existed until somebody ticks the first box."""
    _users(monkeypatch, [u("kyle@wetreadwell.com"), u("will@wetreadwell.com")])
    got = [x["email"] for x in profiles.list_estimators()]
    assert got == ["kyle@wetreadwell.com", "will@wetreadwell.com"]


def test_one_tick_switches_the_list_over(monkeypatch):
    _users(monkeypatch, [u("kyle@wetreadwell.com", estimator=True), u("will@wetreadwell.com")])
    assert [x["email"] for x in profiles.list_estimators()] == ["kyle@wetreadwell.com"]


def test_an_admin_can_also_be_an_estimator(monkeypatch):
    """Hanz's actual requirement — the reason this is a flag and not a role."""
    _users(monkeypatch, [u("hanz@wetreadwell.com", role="super_admin", estimator=True),
                         u("will@wetreadwell.com", role="admin", estimator=True),
                         u("kyle@wetreadwell.com", role="user", estimator=True)])
    assert len(profiles.list_estimators()) == 3


def test_a_paused_person_is_never_assignable(monkeypatch):
    """Deactivating somebody in Admin is the quickest way off every picker, and it must
    win over a stale flag nobody remembered to untick."""
    _users(monkeypatch, [u("kyle@wetreadwell.com", estimator=True),
                         u("gone@wetreadwell.com", estimator=True, status="paused")])
    assert [x["email"] for x in profiles.list_estimators()] == ["kyle@wetreadwell.com"]


def test_a_banned_person_is_never_assignable(monkeypatch):
    _users(monkeypatch, [u("kyle@wetreadwell.com", estimator=True),
                         u("bad@wetreadwell.com", estimator=True, banned="2026-07-01T00:00:00Z")])
    assert [x["email"] for x in profiles.list_estimators()] == ["kyle@wetreadwell.com"]


def test_the_paused_exclusion_applies_to_the_fallback_too(monkeypatch):
    """Otherwise the pre-flag fallback would quietly re-offer somebody who left."""
    _users(monkeypatch, [u("kyle@wetreadwell.com"), u("gone@wetreadwell.com", status="paused")])
    assert [x["email"] for x in profiles.list_estimators()] == ["kyle@wetreadwell.com"]


def test_a_profile_with_no_email_cannot_be_assigned(monkeypatch):
    _users(monkeypatch, [{"id": "x", "email": None, "status": "active", "is_estimator": True}])
    assert profiles.list_estimators() == []


# ── the picker endpoint ─────────────────────────────────────────────────────
def test_the_picker_serves_the_roster(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"email": e, "role": "user"})
    _users(monkeypatch, [u("kyle@wetreadwell.com", estimator=True, name="Kyle Loseke"),
                         u("will@wetreadwell.com")])
    got = client.get("/api/estimators").json()["estimators"]
    assert got == [{"email": "kyle@wetreadwell.com", "name": "Kyle Loseke"}]


def test_the_files_page_still_loads_when_the_roster_lookup_fails(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email", lambda e: {"email": e, "role": "user"})

    def boom():
        raise RuntimeError("supabase down")

    monkeypatch.setattr(profiles, "list_estimators", boom)
    r = client.get("/api/estimators")
    assert r.status_code == 200 and r.json()["estimators"] == []


# ── toggling ────────────────────────────────────────────────────────────────
def _admin(monkeypatch, target):
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "me", "email": e, "role": "admin"})
    monkeypatch.setattr(profiles, "get_by_id", lambda i: target)
    cap = {}

    class _Q:
        def update(self, patch): cap["patch"] = patch; return self
        def eq(self, *a): return self
        def execute(self): return type("R", (), {"data": [target]})()

    monkeypatch.setattr(profiles, "get_client",
                        lambda: type("C", (), {"table": lambda s, n: _Q()})())
    monkeypatch.setattr(main.drafts, "log_event", lambda *a, **k: None)
    return cap


def test_adding_and_removing_writes_the_flag(monkeypatch):
    cap = _admin(monkeypatch, u("kyle@wetreadwell.com"))
    r = client.put("/api/admin/users/kyle/estimator", json={"is_estimator": True})
    assert r.status_code == 200 and r.json()["is_estimator"] is True
    assert cap["patch"] == {"is_estimator": True}

    cap2 = _admin(monkeypatch, u("kyle@wetreadwell.com", estimator=True))
    r = client.put("/api/admin/users/kyle/estimator", json={"is_estimator": False})
    assert r.json()["is_estimator"] is False
    assert cap2["patch"] == {"is_estimator": False}


def test_only_an_admin_can_change_the_roster(monkeypatch):
    monkeypatch.setattr(profiles, "get_by_email",
                        lambda e: {"id": "me", "email": e, "role": "user"})
    assert client.put("/api/admin/users/kyle/estimator",
                      json={"is_estimator": True}).status_code == 403


def test_an_unknown_user_is_reported_not_written(monkeypatch):
    cap = _admin(monkeypatch, None)
    r = client.put("/api/admin/users/nope/estimator", json={"is_estimator": True})
    assert r.json()["ok"] is False
    assert "patch" not in cap


def test_an_admin_may_flag_a_fellow_admin_and_themselves(monkeypatch):
    """Role, ban and delete are guarded by _can_act, which protects the super admin and
    forbids acting on yourself — right for privileges, wrong here. Being assignable IS
    not a privilege, and an admin who also estimates has to tick their own box."""
    cap = _admin(monkeypatch, u("hanz@wetreadwell.com", role="super_admin"))
    r = client.put("/api/admin/users/hanz/estimator", json={"is_estimator": True})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert cap["patch"] == {"is_estimator": True}


def test_the_change_is_logged(monkeypatch):
    _admin(monkeypatch, u("kyle@wetreadwell.com"))
    seen = []
    monkeypatch.setattr(main.drafts, "log_event",
                        lambda pid, actor, action, detail=None: seen.append((action, detail)))
    client.put("/api/admin/users/kyle/estimator", json={"is_estimator": True})
    client.put("/api/admin/users/kyle/estimator", json={"is_estimator": False})
    assert [a for a, _ in seen] == ["estimator_added", "estimator_removed"]


# ── the schema + the Admin UI ───────────────────────────────────────────────
def test_the_column_is_recorded_in_the_schema_file():
    """Staging applies this by hand and prod needs the owner to run it, so the file is
    the only record of what a fresh database needs."""
    import pathlib
    sql = (pathlib.Path(__file__).resolve().parents[1] / "supabase_schema.sql"
           ).read_text(encoding="utf-8")
    assert "add column if not exists is_estimator boolean not null default false" in sql


def test_the_admin_page_offers_the_toggle():
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2] / "frontend"
    js = (root / "js" / "admin.js").read_text(encoding="utf-8")
    assert 'data-act="estimator"' in js and "est-tog" in js
    assert "/estimator`" in js
    # Built by innerHTML and dispatched by data-act; a missing rule renders unstyled.
    assert ".est-tog{" in (root / "admin.html").read_text(encoding="utf-8")
