"""bd/auth.py: BD's people table (the BD login) and the BD role helpers (#806).

BD's test_auth, ported. Its token-check table is gone with BD's own token check: BD trusts the
proposal tool's gate, and tests/test_bd_token_tampering.py sends hostile tokens through the tool's
real verifier instead. What stays is what BD still owns: who has a BD login, the bootstrap from
BD_SUPER_ADMIN_EMAIL / BD_ADMIN_EMAILS, the five BD roles and their checks, and who may change a
BD login (Q29: only a super admin changes another admin).
"""
from __future__ import annotations

import datetime as dt
import types

import pytest

from bd import auth
from bd import config as bd_config
from bd.errors import ApiError


def _identity_for(email, name=None):
    """What the tool's gate keeps on the request (supabase_client.identity_of)."""
    return {"email": email, "sub": "sub-" + email, "name": name}


# ── resolve_user: the BD login table and the bootstrap ───────────────────────────────────────
def test_a_known_active_login_is_returned_and_seen(bd_db):
    bd_db.execute("insert into bd.users (id, email, name, role) values"
                  " (1, 'pat.lee@example.com', 'Pat Lee', 'salesperson')")
    u = auth.resolve_user(bd_db, _identity_for("pat.lee@example.com"))
    assert (u["id"], u["role"], u["name"]) == (1, "salesperson", "Pat Lee")
    assert u["last_seen_at"] is not None and u["auth_sub"] == "sub-pat.lee@example.com"


def test_a_turned_off_login_is_403(bd_db):
    bd_db.execute("insert into bd.users (email, name, role, active) values"
                  " ('sam.ortiz@example.com', 'Sam Ortiz', 'manager', false)")
    with pytest.raises(ApiError) as e:
        auth.resolve_user(bd_db, _identity_for("sam.ortiz@example.com"))
    assert e.value.status == 403 and e.value.message == auth.TURNED_OFF


def test_a_signed_in_staffer_with_no_bd_login_is_403_not_401(bd_db):
    """A valid sign-in with no BD role: 403, so the page says so instead of bouncing to sign-in."""
    with pytest.raises(ApiError) as e:
        auth.resolve_user(bd_db, _identity_for("new.hire@example.com"))
    assert e.value.status == 403 and e.value.message == auth.NO_BD_ROLE
    assert bd_db.execute("select count(*) as n from bd.users").fetchone()["n"] == 0


def test_no_email_is_401(bd_db):
    for identity in ({}, {"email": ""}, {"email": "   "}):
        with pytest.raises(ApiError) as e:
            auth.resolve_user(bd_db, identity)
        assert e.value.status == 401


def test_bootstrap_super_admin_and_admins_on_first_sign_in(bd_db, monkeypatch):
    monkeypatch.setattr(bd_config, "BD_SUPER_ADMIN_EMAIL", "owner@example.com")
    monkeypatch.setattr(bd_config, "BD_ADMIN_EMAILS", frozenset({"test.admin@example.com", "owner@example.com"}))
    owner = auth.resolve_user(bd_db, _identity_for("owner@example.com", "Robin Example"))
    assert owner["role"] == "super_admin" and owner["name"] == "Robin Example"
    adm = auth.resolve_user(bd_db, _identity_for("test.admin@example.com"))
    assert adm["role"] == "admin" and adm["name"] == "Test Admin"       # no display name: from the email
    again = auth.resolve_user(bd_db, _identity_for("owner@example.com"))
    assert again["id"] == owner["id"]
    assert bd_db.execute("select count(*) as n from bd.users").fetchone()["n"] == 2


def test_the_tools_own_super_admin_setting_opens_no_bd_door(bd_db, monkeypatch):
    """BD reads only BD_SUPER_ADMIN_EMAIL / BD_ADMIN_EMAILS; the tool's SUPER_ADMIN_EMAIL is not a BD
    role (Q30: a proposal-tool admin gets no BD role automatically)."""
    monkeypatch.setenv("SUPER_ADMIN_EMAIL", "tool.owner@example.com")
    monkeypatch.setenv("ADMIN_EMAILS", "tool.owner@example.com")
    monkeypatch.setattr(bd_config, "BD_SUPER_ADMIN_EMAIL", "")
    monkeypatch.setattr(bd_config, "BD_ADMIN_EMAILS", frozenset())
    with pytest.raises(ApiError) as e:
        auth.resolve_user(bd_db, _identity_for("tool.owner@example.com"))
    assert e.value.status == 403


def test_bootstrap_never_changes_an_existing_logins_role(bd_db, monkeypatch):
    bd_db.execute("insert into bd.users (email, name, role) values ('lee.park@example.com', 'Lee Park', 'manager')")
    monkeypatch.setattr(bd_config, "BD_ADMIN_EMAILS", frozenset({"lee.park@example.com"}))
    assert auth.resolve_user(bd_db, _identity_for("lee.park@example.com"))["role"] == "manager"


def test_last_seen_is_refreshed_at_most_once_a_minute(bd_db):
    bd_db.execute("insert into bd.users (email, name, role, last_seen_at) values"
                  " ('pat.lee@example.com', 'Pat Lee', 'salesperson', now() - interval '1 hour')")
    first = auth.resolve_user(bd_db, _identity_for("pat.lee@example.com"))["last_seen_at"]
    second = auth.resolve_user(bd_db, _identity_for("pat.lee@example.com"))["last_seen_at"]
    assert first == second
    assert first > dt.datetime.now(dt.UTC) - dt.timedelta(minutes=30)


def test_current_user_needs_the_gates_identity():
    """No identity on the request (a path the gate waved through) is 401, before any database work."""
    for state in (types.SimpleNamespace(), types.SimpleNamespace(auth_identity=None),
                  types.SimpleNamespace(auth_identity={"email": ""})):
        with pytest.raises(ApiError) as e:
            auth.current_user(types.SimpleNamespace(state=state))
        assert e.value.status == 401 and e.value.message == auth.NOT_SIGNED_IN


# ── roles ─────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role,want", [
    ("salesperson", {"send": True, "analytics": False, "admin": False, "admin_area": False, "import": True, "run_batch": False, "week": True, "pick_owner": False, "add_contact": True, "edit_contact": True, "clear_duplicate": False, "cadence": True, "manage_entries": False}),
    ("assistant", {"send": False, "analytics": False, "admin": False, "admin_area": True, "import": True, "run_batch": False, "week": False, "pick_owner": False, "add_contact": True, "edit_contact": True, "clear_duplicate": True, "cadence": True, "manage_entries": False}),
    ("manager", {"send": False, "analytics": True, "admin": False, "admin_area": False, "import": False, "run_batch": False, "week": True, "pick_owner": True, "add_contact": False, "edit_contact": False, "clear_duplicate": False, "cadence": True, "manage_entries": False}),
    ("admin", {"send": True, "analytics": True, "admin": True, "admin_area": True, "import": True, "run_batch": True, "week": True, "pick_owner": True, "add_contact": True, "edit_contact": True, "clear_duplicate": True, "cadence": True, "manage_entries": True}),
    ("super_admin", {"send": True, "analytics": True, "admin": True, "admin_area": True, "import": True, "run_batch": True, "week": True, "pick_owner": True, "add_contact": True, "edit_contact": True, "clear_duplicate": True, "cadence": True, "manage_entries": True}),
])
def test_can_matches_the_contract_table(role, want):
    assert auth.can({"role": role}) == want


def test_has_role_lets_admins_through_everything():
    assert auth.has_role({"role": "admin"}, "salesperson")
    assert auth.has_role({"role": "super_admin"})
    assert not auth.has_role({"role": "manager"})
    assert auth.has_role({"role": "manager"}, "manager", "assistant")
    assert not auth.has_role({"role": "assistant"}, "salesperson")
    assert not auth.has_role(None, "salesperson")


def test_require_role_refuses_with_403():
    check = auth.require_role("salesperson")
    assert check(user={"role": "salesperson"})["role"] == "salesperson"
    assert check(user={"role": "admin"})["role"] == "admin"
    with pytest.raises(ApiError) as e:
        check(user={"role": "assistant"})
    assert e.value.status == 403 and e.value.message == "Your role can't do that."
    with pytest.raises(ApiError):
        auth.require_role()(user={"role": "manager"})


# ── who may change a BD login (Q29) ──────────────────────────────────────────────────────────
SUPER = {"id": 1, "role": "super_admin"}
ADMIN = {"id": 2, "role": "admin"}
OTHER_ADMIN = {"id": 3, "role": "admin", "active": True}
SALES = {"id": 4, "role": "salesperson", "active": True}


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_only_a_super_admin_adds_an_admin(role):
    assert auth.refuse_new_login(SUPER, role) is None
    assert auth.refuse_new_login(ADMIN, role) == auth.ONLY_SUPER_ADDS_ADMIN


@pytest.mark.parametrize("role", ["salesperson", "assistant", "manager"])
def test_any_bd_admin_adds_the_other_roles(role):
    assert auth.refuse_new_login(ADMIN, role) is None and auth.refuse_new_login(SUPER, role) is None


@pytest.mark.parametrize("changes", [{"active": False}, {"role": "manager"}, {"name": "New Name"}])
def test_only_a_super_admin_changes_another_admins_login(changes):
    assert auth.refuse_login_change(ADMIN, OTHER_ADMIN, changes) == auth.ONLY_SUPER_CHANGES_ADMIN
    assert auth.refuse_login_change(SUPER, OTHER_ADMIN, changes) is None


def test_only_a_super_admin_makes_someone_an_admin():
    assert auth.refuse_login_change(ADMIN, SALES, {"role": "admin"}) == auth.ONLY_SUPER_CHANGES_ADMIN
    assert auth.refuse_login_change(ADMIN, SALES, {"role": "super_admin"}) == auth.ONLY_SUPER_CHANGES_ADMIN
    assert auth.refuse_login_change(SUPER, SALES, {"role": "admin"}) is None


def test_an_admin_changes_a_non_admins_login():
    assert auth.refuse_login_change(ADMIN, SALES, {"active": False}) is None
    assert auth.refuse_login_change(ADMIN, SALES, {"role": "manager", "name": "Sam"}) is None


def test_nobody_changes_their_own_role_or_sign_in_but_the_name_is_fine():
    for me in (SUPER, ADMIN):
        own = dict(me, active=True)
        assert auth.refuse_login_change(me, own, {"active": False}) == auth.NOT_YOUR_OWN
        assert auth.refuse_login_change(me, own, {"role": "manager"}) == auth.NOT_YOUR_OWN
        assert auth.refuse_login_change(me, own, {"name": "A New Name"}) is None
        assert auth.refuse_login_change(me, own, {"role": me["role"], "active": True}) is None
