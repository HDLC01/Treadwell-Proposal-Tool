"""BD's Admin routes on the proposal tool's app (#809), against the real app and a real Postgres.

    GET/POST /api/bd/admin/users, PATCH /api/bd/admin/users/{id}, PUT /api/bd/admin/settings,
    GET /api/bd/admin/telephony, GET /api/bd/admin/unmatched-calls, POST .../{id}/attach|dismiss

BD's test_admin_api, ported. BD compared its main answers with its mock api.js; the mock was retired
in #806, so every answer here is written out by hand from the fixture seed (bd/ops/fixture_seed.py):

    users  1 Avery Quill (salesperson)  2 Blair Fenn (salesperson)  3 Casey Moret (assistant)
           4 Devon Hale (manager)       5 Emery Stoll (admin)       6 Frankie Oduya (super admin)
           7 Gale Ward (salesperson, login turned off)
    the unmatched call 801: 95 s from +19135550199, 2026-11-03 16:42 CST
    contact 32 Wes Calder at Osage Plains Brewing (18): no owner, 913-555-0112, nothing logged

People are added on the tool's sign-in domain (bd.auth.sign_in_domain, the one seam to the tool's
gate, which reads supabase_client.ALLOWED_DOMAIN): example.com here, so everyone is made up. Who
may call each route is the role table in test_bd_admin_roles.py; the People table's separation
from the tool's own people is there too.
"""
from __future__ import annotations

import copy

import pytest

from bd import auth as bd_auth
from bd import config as bd_config
from bd import serialize

AVERY, BLAIR, CASEY, DEVON, EMERY, FRANKIE, GALE = 1, 2, 3, 4, 5, 6, 7
CALL = 801
WES = 32
ADD = "Use a @example.com address."
REAL_SIGN_IN_DOMAIN = bd_auth.sign_in_domain


@pytest.fixture(autouse=True)
def sign_in_domain(monkeypatch):
    """The tool's gate lets in @example.com, so a BD login can only be made for one."""
    monkeypatch.setattr(bd_auth, "sign_in_domain", lambda: "example.com")


def envelope(r, status, code, message=None, fields=None):
    assert r.status_code == status, r.text
    body = r.json()
    assert body["ok"] is False and body["error"] == code, body
    assert isinstance(body["message"], str) and body["message"][-1] in ".?!", body
    if message is not None:
        assert body["message"] == message, body
    if fields is not None:
        assert body.get("fields") == fields, body
    return body


def ok(r, status=200):
    assert r.status_code == status, r.text
    body = r.json()
    assert body["ok"] is True, body
    return body


def strip_seen(u):
    return {k: v for k, v in u.items() if k != "last_seen_at"}


def add_unmatched(db, **kw):
    row = {"provider": "quo", "external_id": None, "kind": "call", "direction": "in",
           "from_e164": "+19135550188", "occurred_at": "2026-11-03T15:00:00-06:00", "duration_s": 30,
           "summary": "Test call.", "status": "open"}
    row.update(kw)
    cols = list(row)
    return db.execute(
        "insert into bd.unmatched_calls (" + ", ".join(cols) + ") values (" + ", ".join(["%s"] * len(cols))
        + ") returning id", [row[c] for c in cols]).fetchone()["id"]


def count(db, sql, params=()):
    return db.execute("select count(*) as n from " + sql, params).fetchone()["n"]


# ── GET /api/bd/admin/users ──────────────────────────────────────────────────────────────────
# Each person's last sign-in, in Central: 15:02 UTC on 3 Nov is 09:02 CST; 21:15 UTC on 30 Oct is
# 16:15 CDT (the clocks went back on 1 Nov); 16:00 UTC on 12 Mar is 11:00 CDT (forward on 8 Mar).
SEEDED_USERS = [
    {"id": 1, "name": "Avery Quill", "email": "avery.quill@example.com", "role": "salesperson", "active": True,
     "last_seen_at": "2026-11-03T09:02:00-06:00"},
    {"id": 2, "name": "Blair Fenn", "email": "blair.fenn@example.com", "role": "salesperson", "active": True,
     "last_seen_at": None},
    {"id": 3, "name": "Casey Moret", "email": "casey.moret@example.com", "role": "assistant", "active": True,
     "last_seen_at": "2026-11-02T08:30:00-06:00"},
    {"id": 4, "name": "Devon Hale", "email": "devon.hale@example.com", "role": "manager", "active": True,
     "last_seen_at": "2026-10-30T16:15:00-05:00"},
    {"id": 5, "name": "Emery Stoll", "email": "emery.stoll@example.com", "role": "admin", "active": True,
     "last_seen_at": None},
    {"id": 6, "name": "Frankie Oduya", "email": "frankie.oduya@example.com", "role": "super_admin", "active": True,
     "last_seen_at": None},
    {"id": 7, "name": "Gale Ward", "email": "gale.ward@example.com", "role": "salesperson", "active": False,
     "last_seen_at": "2026-03-12T11:00:00-05:00"},
]


def test_the_people_list_has_everyone_turned_off_logins_too(bd_seeded, bd_as_user, bd_db):
    body = ok(bd_as_user(EMERY).get("/api/bd/admin/users"))
    assert body["total"] == 7
    # Signing in refreshes only the caller's own last_seen_at (Emery, 5).
    assert [u if u["id"] != EMERY else dict(u, last_seen_at=None) for u in body["items"]] == SEEDED_USERS
    assert body["items"][EMERY - 1]["last_seen_at"] is not None
    bd_db.execute("update bd.users set active = false where id = %s", (DEVON,))
    body = ok(bd_as_user(FRANKIE).get("/api/bd/admin/users"))
    assert [u["active"] for u in body["items"] if u["id"] == DEVON] == [False]
    assert body["total"] == 7


# ── POST /api/bd/admin/users ─────────────────────────────────────────────────────────────────
def test_adding_a_person_and_they_can_sign_in(bd_seeded, bd_as_user, bd_client):
    body = ok(bd_as_user(FRANKIE).post("/api/bd/admin/users",
                                       json={"email": "nell.ash@example.com", "name": "Nell Ash",
                                             "role": "salesperson"}))
    assert body["user"] == {"id": 8, "name": "Nell Ash", "email": "nell.ash@example.com", "role": "salesperson",
                            "active": True, "last_seen_at": None}
    me = ok(bd_client.get("/api/bd/me", headers={"Authorization": "Bearer test:nell.ash@example.com"}))
    assert me["user"]["role"] == "salesperson"


def test_adding_trims_lowercases_names_from_the_email_and_logs_it(bd_seeded, bd_as_user, bd_db):
    ok(bd_as_user(FRANKIE).post("/api/bd/admin/users",
                                json={"email": "nell.ash@example.com", "name": "Nell Ash", "role": "salesperson"}))
    body = ok(bd_as_user(FRANKIE).post("/api/bd/admin/users",
                                       json={"email": " Rue.Tamsin@Example.COM ", "role": "manager"}))
    assert body["user"] == {"id": 9, "name": "Rue Tamsin", "email": "rue.tamsin@example.com", "role": "manager",
                            "active": True, "last_seen_at": None}
    ev = bd_db.execute("select actor_id, contact_id, data from bd.events where kind = 'user_added' order by id").fetchall()
    assert [(e["actor_id"], e["contact_id"], e["data"]) for e in ev] == [
        (FRANKIE, None, {"user_id": 8, "role": "salesperson"}), (FRANKIE, None, {"user_id": 9, "role": "manager"})]


@pytest.mark.parametrize("payload,fields", [
    ({"email": "nell@elsewhere.example.org", "role": "salesperson"}, {"email": ADD}),
    ({"email": "nell@example.com.example.org", "role": "salesperson"}, {"email": ADD}),
    ({"email": "nell@sub.example.com", "role": "salesperson"}, {"email": ADD}),
    ({"email": "two@at@example.com", "role": "salesperson"}, {"email": ADD}),
    ({"email": "", "role": "salesperson"}, {"email": ADD}),
    ({"role": "salesperson"}, {"email": ADD}),
    ({"email": 7, "role": "salesperson"}, {"email": ADD}),
    # 243 + 12 = 255 characters: one past the longest address mail allows (RFC 5321's 254).
    ({"email": "n" * 243 + "@example.com", "role": "salesperson"}, {"email": "Use at most 254 characters."}),
    ({"email": "nell@example.com"}, {"role": "Pick a role."}),
    ({"email": "nell@example.com", "role": "boss"}, {"role": "Pick a role."}),
    ({"email": "nell@example.com", "role": "user"}, {"role": "Pick a role."}),
    ({"email": "nell@example.com", "role": "salesperson", "name": 5}, {"name": "Use text."}),
    ({"email": "nell@example.com", "role": "salesperson", "name": "x" * 121}, {"name": "Use at most 120 characters."}),
    ({}, {"email": ADD, "role": "Pick a role."}),
])
def test_adding_with_bad_input_is_400_and_adds_nobody(bd_seeded, bd_as_user, bd_db, payload, fields):
    envelope(bd_as_user(FRANKIE).post("/api/bd/admin/users", json=payload), 400, "bad_request",
             "Some fields need fixing.", fields)
    assert count(bd_db, "bd.users") == 7


def test_a_name_of_exactly_120_characters_is_kept(bd_seeded, bd_as_user):
    body = ok(bd_as_user(EMERY).post("/api/bd/admin/users",
                                     json={"email": "nell@example.com", "role": "assistant", "name": "n" * 120}))
    assert body["user"]["name"] == "n" * 120


def test_an_email_of_exactly_254_characters_is_kept(bd_seeded, bd_as_user):
    email = "n" * 242 + "@example.com"                  # 242 + 12 = 254
    body = ok(bd_as_user(EMERY).post("/api/bd/admin/users", json={"email": email, "role": "assistant", "name": "Nell"}))
    assert body["user"]["email"] == email


def test_the_domain_is_the_tools_sign_in_domain(bd_seeded, bd_as_user, monkeypatch):
    """BD's allowed-domain setting was not carried (#802): a login is made only for an address the
    tool's gate lets in. The real seam this time, reading the gate's own setting."""
    import supabase_client

    monkeypatch.setattr(bd_auth, "sign_in_domain", REAL_SIGN_IN_DOMAIN)
    monkeypatch.setattr(supabase_client, "ALLOWED_DOMAIN", "@Treadwell.Example.NET ")
    envelope(bd_as_user(EMERY).post("/api/bd/admin/users", json={"email": "nell@example.com", "role": "assistant"}),
             400, "bad_request", fields={"email": "Use a @treadwell.example.net address."})
    ok(bd_as_user(EMERY).post("/api/bd/admin/users", json={"email": "nell@treadwell.example.net", "role": "assistant"}))


def test_adding_with_a_body_that_is_not_an_object_is_400(bd_seeded, bd_as_user):
    envelope(bd_as_user(FRANKIE).post("/api/bd/admin/users", json=["nell@example.com"]), 400, "bad_request",
             fields={"body": "Send a JSON object."})
    r = bd_as_user(FRANKIE).post("/api/bd/admin/users", content=b"{not json",
                                 headers={"Content-Type": "application/json"})
    envelope(r, 400, "bad_request")


@pytest.mark.parametrize("email", ["avery.quill@example.com", "AVERY.QUILL@example.com", "  avery.quill@EXAMPLE.com",
                                   "gale.ward@example.com"])
def test_adding_someone_who_already_has_a_login_is_409(bd_seeded, bd_as_user, email):
    envelope(bd_as_user(FRANKIE).post("/api/bd/admin/users", json={"email": email, "role": "manager"}),
             409, "conflict", "That person already has a login.")


@pytest.mark.parametrize("role", ["admin", "super_admin"])
def test_only_a_super_admin_adds_an_admin(bd_seeded, bd_as_user, bd_db, role):
    envelope(bd_as_user(EMERY).post("/api/bd/admin/users", json={"email": "new.admin@example.com", "role": role}),
             403, "forbidden", "Only a super admin can add an admin.")
    assert count(bd_db, "bd.users") == 7
    body = ok(bd_as_user(FRANKIE).post("/api/bd/admin/users", json={"email": "new.admin@example.com", "role": role}))
    assert body["user"]["role"] == role and body["user"]["name"] == "New Admin"


def test_a_plain_admin_adds_every_other_role(bd_seeded, bd_as_user):
    for n, role in enumerate(("salesperson", "assistant", "manager")):
        body = ok(bd_as_user(EMERY).post("/api/bd/admin/users", json={"email": "p%d@example.com" % n, "role": role}))
        assert body["user"]["role"] == role and body["user"]["active"] is True


# ── PATCH /api/bd/admin/users/{id} ───────────────────────────────────────────────────────────
def test_a_patch_that_changes_nothing_answers_the_person(bd_seeded, bd_as_user, bd_db):
    body = ok(bd_as_user(FRANKIE).patch("/api/bd/admin/users/4", json={"role": "manager", "active": True}))
    assert body["user"] == SEEDED_USERS[DEVON - 1]
    ok(bd_as_user(FRANKIE).patch("/api/bd/admin/users/1", json={"role": "salesperson", "active": True, "unknown": 1}))
    ok(bd_as_user(FRANKIE).patch("/api/bd/admin/users/1", json={}))
    assert count(bd_db, "bd.events where kind = 'user_changed'") == 0


def test_a_patch_changes_role_sign_in_and_name_and_logs_it(bd_seeded, bd_as_user, bd_client, bd_db):
    body = ok(bd_as_user(EMERY).patch("/api/bd/admin/users/4", json={"role": "assistant", "name": "  Devon H. "}))
    assert body["user"]["role"] == "assistant" and body["user"]["name"] == "Devon H."
    body = ok(bd_as_user(EMERY).patch("/api/bd/admin/users/4", json={"active": False}))
    assert body["user"]["active"] is False
    # A turned-off login is refused everywhere at once.
    devon = {"Authorization": "Bearer test:devon.hale@example.com"}
    envelope(bd_client.get("/api/bd/me", headers=devon), 403, "forbidden",
             "Your BD login is turned off. Ask a BD admin to turn it back on.")
    ok(bd_as_user(EMERY).patch("/api/bd/admin/users/4", json={"active": True}))
    ok(bd_client.get("/api/bd/me", headers=devon))
    ev = bd_db.execute("select actor_id, data from bd.events where kind = 'user_changed' order by id").fetchall()
    assert [e["data"] for e in ev] == [
        {"user_id": 4, "changes": {"role": {"from": "manager", "to": "assistant"},
                                   "name": {"from": "Devon Hale", "to": "Devon H."}}},
        {"user_id": 4, "changes": {"active": {"from": True, "to": False}}},
        {"user_id": 4, "changes": {"active": {"from": False, "to": True}}},
    ]
    assert {e["actor_id"] for e in ev} == {EMERY}


def test_a_turned_off_login_is_turned_back_on(bd_seeded, bd_as_user, bd_client):
    envelope(bd_client.get("/api/bd/me", headers={"Authorization": "Bearer test:gale.ward@example.com"}), 403,
             "forbidden")
    ok(bd_as_user(EMERY).patch("/api/bd/admin/users/7", json={"active": True}))
    assert ok(bd_client.get("/api/bd/me", headers={"Authorization": "Bearer test:gale.ward@example.com"})
              )["user"]["role"] == "salesperson"


@pytest.mark.parametrize("path", ["/api/bd/admin/users/999", "/api/bd/admin/users/0",
                                  "/api/bd/admin/users/99999999999999999999", "/api/bd/admin/users/abc",
                                  "/api/bd/admin/users/%205"])
def test_patching_someone_who_does_not_exist_is_404(bd_seeded, bd_as_user, path):
    envelope(bd_as_user(FRANKIE).patch(path, json={"name": "X"}), 404, "not_found", "That user does not exist.")


@pytest.mark.parametrize("who", [EMERY, FRANKIE])
@pytest.mark.parametrize("change", [{"role": "manager"}, {"active": False}, {"role": "salesperson", "active": False},
                                    {"name": "Me", "active": False}])
def test_nobody_changes_their_own_role_or_sign_in(bd_seeded, bd_as_user, bd_db, who, change):
    before = bd_db.execute("select role, active, name from bd.users where id = %s", (who,)).fetchone()
    envelope(bd_as_user(who).patch("/api/bd/admin/users/%d" % who, json=change), 403, "forbidden",
             "You can't change your own role or sign-in.")
    assert bd_db.execute("select role, active, name from bd.users where id = %s", (who,)).fetchone() == before


@pytest.mark.parametrize("who,role", [(FRANKIE, "super_admin"), (EMERY, "admin")])
def test_your_own_name_is_fine(bd_seeded, bd_as_user, who, role):
    body = ok(bd_as_user(who).patch("/api/bd/admin/users/%d" % who, json={"name": "Renamed", "role": role,
                                                                          "active": True}))
    assert body["user"]["name"] == "Renamed" and body["user"]["role"] == role


# Q29: only a super admin changes another admin. Target 8 is a second plain admin, 9 a second super admin.
@pytest.mark.parametrize("target,change", [
    (FRANKIE, {"name": "Not Frankie"}),          # the super admin
    (FRANKIE, {"active": False}),
    (8, {"role": "manager"}),                    # another plain admin
    (8, {"name": "Renamed Admin"}),
    (9, {"active": False}),                      # another super admin
    (AVERY, {"role": "admin"}),                  # promoting someone
    (AVERY, {"role": "super_admin"}),
])
def test_only_a_super_admin_changes_an_admin(bd_seeded, bd_as_user, bd_db, target, change):
    bd_db.execute("insert into bd.users (id, email, name, role) overriding system value values"
                  " (8, 'other.admin@example.com', 'Other Admin', 'admin'),"
                  " (9, 'other.super@example.com', 'Other Super', 'super_admin')")
    before = bd_db.execute("select role, active, name from bd.users where id = %s", (target,)).fetchone()
    envelope(bd_as_user(EMERY).patch("/api/bd/admin/users/%d" % target, json=change), 403, "forbidden",
             "Only a super admin can change an admin.")
    assert bd_db.execute("select role, active, name from bd.users where id = %s", (target,)).fetchone() == before
    super_admin = FRANKIE if target != FRANKIE else 9
    body = ok(bd_as_user(super_admin).patch("/api/bd/admin/users/%d" % target, json=change))
    for k, v in change.items():
        assert body["user"][k] == v


def test_the_super_admin_demotes_and_turns_off_an_admin(bd_seeded, bd_as_user, bd_client):
    body = ok(bd_as_user(FRANKIE).patch("/api/bd/admin/users/5", json={"role": "manager"}))
    assert body["user"]["role"] == "manager"
    envelope(bd_as_user(EMERY).get("/api/bd/admin/users"), 403, "forbidden", "Your role can't do that.")
    ok(bd_as_user(FRANKIE).patch("/api/bd/admin/users/5", json={"active": False}))
    envelope(bd_client.get("/api/bd/me", headers={"Authorization": "Bearer test:emery.stoll@example.com"}), 403,
             "forbidden")


def test_a_plain_admin_still_changes_everyone_who_is_not_an_admin(bd_seeded, bd_as_user):
    for uid, change in ((AVERY, {"name": "Avery Q."}), (CASEY, {"role": "manager"}), (DEVON, {"active": False})):
        body = ok(bd_as_user(EMERY).patch("/api/bd/admin/users/%d" % uid, json=change))
        for k, v in change.items():
            assert body["user"][k] == v


@pytest.mark.parametrize("change,message,fields", [
    ({"role": "boss"}, "Pick a role.", {"role": "Unknown role."}),
    ({"role": None}, "Pick a role.", {"role": "Unknown role."}),
    ({"active": "no"}, "Use true or false.", {"active": "Use true or false."}),
    ({"active": 0}, "Use true or false.", {"active": "Use true or false."}),
    ({"name": "   "}, "Use a name.", {"name": "Use a name."}),
    ({"name": None}, "Use a name.", {"name": "Use a name."}),
    ({"name": "x" * 121}, "Use at most 120 characters.", {"name": "Use at most 120 characters."}),
    ({"role": "boss", "name": ""}, "Some fields need fixing.", {"role": "Unknown role.", "name": "Use a name."}),
])
def test_a_bad_patch_is_400_and_changes_nothing(bd_seeded, bd_as_user, bd_db, change, message, fields):
    before = bd_db.execute("select role, active, name from bd.users where id = 1").fetchone()
    envelope(bd_as_user(FRANKIE).patch("/api/bd/admin/users/1", json=change), 400, "bad_request", message, fields)
    assert bd_db.execute("select role, active, name from bd.users where id = 1").fetchone() == before


def test_a_patch_body_that_is_not_an_object_is_400(bd_seeded, bd_as_user):
    envelope(bd_as_user(FRANKIE).patch("/api/bd/admin/users/1", json=[1]), 400, "bad_request",
             fields={"body": "Send a JSON object."})


# ── PUT /api/bd/admin/settings ───────────────────────────────────────────────────────────────
CONTRACT_PUT = {"bd_cadence": "monthly", "default_frequency": {"maintenance": 3},
                "lead_sources": ["Current Account", "DSBC Sales", "Website Lead", "Other/Misc", "Trade Show"]}


def test_a_put_is_read_back_by_every_role_and_logged(bd_seeded, bd_as_user, bd_db):
    before = ok(bd_as_user(AVERY).get("/api/bd/settings"))["settings"]
    body = ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json=CONTRACT_PUT))
    assert body["settings"] == dict(before, bd_cadence="monthly",
                                    lead_sources=["Current Account", "DSBC Sales", "Website Lead", "Other/Misc",
                                                  "Trade Show"])
    for who in (AVERY, CASEY, DEVON):
        assert ok(bd_as_user(who).get("/api/bd/settings"))["settings"] == body["settings"]
    assert bd_db.execute("select updated_by from bd.settings where key = 'lead_sources'").fetchone()["updated_by"] == FRANKIE
    ev = bd_db.execute("select actor_id, data from bd.events where kind = 'settings_changed'").fetchall()
    assert [(e["actor_id"], e["data"]["keys"]) for e in ev] == [
        (FRANKIE, ["bd_cadence", "default_frequency", "lead_sources"])]


def test_weekly_is_merged_key_by_key(bd_seeded, bd_as_user):
    body = ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"weekly": {"new_count": 6, "followup_count": 4}}))
    # The run day, hour and on/off stay the defaults (BD_WEEKLY_ENABLED is off in the tests).
    assert body["settings"]["weekly"] == {"new_count": 6, "followup_count": 4, "run_day": "friday",
                                          "run_hour": 16, "enabled": False}
    body = ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"default_frequency": {"maintenance": 6}}))
    assert body["settings"]["default_frequency"] == {"maintenance": 6}
    assert body["settings"]["weekly"]["new_count"] == 6


def test_default_frequency_bd_is_retired(bd_seeded, bd_as_user, bd_db):
    """A client may still send it: it is ignored, never stored, never served."""
    body = ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"default_frequency": {"bd": 6}}))
    assert body["settings"]["default_frequency"] == {"maintenance": 3}
    assert bd_db.execute("select value from bd.settings where key = 'default_frequency'").fetchone()["value"] == \
        {"maintenance": 3}
    bd_db.execute("""update bd.settings set value = '{"bd": 9, "maintenance": 2}' where key = 'default_frequency'""")
    assert ok(bd_as_user(AVERY).get("/api/bd/settings"))["settings"]["default_frequency"] == {"maintenance": 2}


def test_the_bd_cadence_is_saved_as_a_word(bd_seeded, bd_as_user, bd_db):
    assert ok(bd_as_user(AVERY).get("/api/bd/settings"))["settings"]["bd_cadence"] == "quarterly"
    for word in ("weekly", "monthly", "quarterly"):
        body = ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"bd_cadence": word}))
        assert body["settings"]["bd_cadence"] == word
        assert ok(bd_as_user(DEVON).get("/api/bd/settings"))["settings"]["bd_cadence"] == word
    assert bd_db.execute("select value from bd.settings where key = 'bd_cadence'").fetchone()["value"] == "quarterly"


# Rory Sandell (22) follows the global cadence; Lena Ortiz (27) is monthly until 2026-12-31 whatever it
# says; Nora Lindqvist (31) is a maintenance contact with her own 2 a year.
@pytest.mark.parametrize("word,freq", [("weekly", 52), ("monthly", 12), ("quarterly", 4)])
def test_the_bd_cadence_moves_every_bd_contact_but_not_an_override_or_maintenance(bd_seeded, bd_as_user, word, freq):
    ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"bd_cadence": word}))
    got = {c["id"]: c for c in ok(bd_as_user(AVERY).get("/api/bd/contacts?limit=500"))["items"]}
    assert (got[22]["frequency_per_year"], got[22]["cadence"], got[22]["cadence_source"]) == (freq, word, "global")
    assert (got[27]["frequency_per_year"], got[27]["cadence"], got[27]["cadence_source"]) == (12, "monthly", "override")
    assert (got[31]["frequency_per_year"], got[31]["cadence"], got[31]["cadence_source"]) == (2, None, None)


def test_a_bad_put_is_the_envelope_and_changes_nothing(bd_seeded, bd_as_user):
    before = ok(bd_as_user(FRANKIE).get("/api/bd/settings"))["settings"]
    r = bd_as_user(FRANKIE).put("/api/bd/admin/settings",
                                json={"weekly": {"new_count": 6, "followup_count": 6},
                                      "lead_sources": ["Current Account", "DSBC Sales", "Website Lead", "X"]})
    assert r.status_code == 400
    assert r.json() == {"ok": False, "error": "bad_request", "message": "New people and follow-ups must add up to 10.",
                        "fields": {"weekly": "New people and follow-ups must add up to 10."}}
    assert ok(bd_as_user(FRANKIE).get("/api/bd/settings"))["settings"] == before


def test_several_bad_settings_say_some_settings_need_fixing(bd_seeded, bd_as_user):
    body = envelope(bd_as_user(FRANKIE).put("/api/bd/admin/settings",
                                            json={"weekly_meeting_goal": 99, "ai_enabled": "yes"}),
                    400, "bad_request", "Some settings need fixing.")
    assert body["fields"] == {"weekly_meeting_goal": "Use a number from 0 to 50.", "ai_enabled": "Use on or off."}


def test_system_lead_sources_cannot_be_removed(bd_seeded, bd_as_user):
    msg = "DSBC Sales and Website Lead can't be removed: the weekly meeting goal counts on them."
    envelope(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"lead_sources": ["Current Account"]}),
             400, "bad_request", msg, {"lead_sources": msg})
    envelope(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"lead_sources": ["Website Lead", "Current Account"]}),
             400, "bad_request", "DSBC Sales can't be removed: the weekly meeting goal counts on them.")


WEEKLY_SUM = "New people and follow-ups must add up to 10."
WEEKLY_REST = "Pick Friday, Saturday or Sunday, an hour from 0 to 23, and on or off."
FREQ = "Use a number from 1 to 52."
CADENCE = "Pick weekly, monthly or quarterly."
PICK = "Keep at least one value, each one different."
PICK_SIZE = "Keep at most 100 values of 120 characters or fewer."


@pytest.mark.parametrize("change,field,sentence", [
    ({"weekly": {"new_count": 11, "followup_count": -1}}, "weekly", WEEKLY_SUM),
    ({"weekly": {"new_count": 4, "followup_count": 4}}, "weekly", WEEKLY_SUM),
    ({"weekly": {"new_count": 5.5, "followup_count": 4.5}}, "weekly", WEEKLY_SUM),
    ({"weekly": {"new_count": "5"}}, "weekly", WEEKLY_SUM),
    ({"weekly": {"new_count": True, "followup_count": 9}}, "weekly", WEEKLY_SUM),
    ({"weekly": 10}, "weekly", WEEKLY_SUM),
    ({"weekly": None}, "weekly", WEEKLY_SUM),
    ({"weekly": {"run_day": "Friday"}}, "weekly", WEEKLY_REST),
    ({"weekly": {"run_day": "someday"}}, "weekly", WEEKLY_REST),
    # A run before Friday would snooze the list it is about to start (Monday-Thursday).
    ({"weekly": {"run_day": "monday"}}, "weekly", WEEKLY_REST),
    ({"weekly": {"run_day": "thursday"}}, "weekly", WEEKLY_REST),
    ({"weekly": {"run_hour": 24}}, "weekly", WEEKLY_REST),
    ({"weekly": {"run_hour": -1}}, "weekly", WEEKLY_REST),
    ({"weekly": {"run_hour": 9.5}}, "weekly", WEEKLY_REST),
    ({"weekly": {"enabled": "yes"}}, "weekly", WEEKLY_REST),
    ({"default_frequency": {"maintenance": 0}}, "default_frequency", FREQ),
    ({"default_frequency": {"maintenance": 53}}, "default_frequency", FREQ),
    ({"default_frequency": {"maintenance": "3"}}, "default_frequency", FREQ),
    ({"default_frequency": {"maintenance": True}}, "default_frequency", FREQ),
    ({"default_frequency": 4}, "default_frequency", FREQ),
    ({"bd_cadence": "daily"}, "bd_cadence", CADENCE),
    ({"bd_cadence": "Weekly"}, "bd_cadence", CADENCE),
    ({"bd_cadence": " monthly"}, "bd_cadence", CADENCE),
    ({"bd_cadence": ""}, "bd_cadence", CADENCE),
    ({"bd_cadence": 4}, "bd_cadence", CADENCE),
    ({"bd_cadence": True}, "bd_cadence", CADENCE),
    ({"bd_cadence": None}, "bd_cadence", CADENCE),
    ({"bd_cadence": ["weekly"]}, "bd_cadence", CADENCE),
    ({"weekly_meeting_goal": 51}, "weekly_meeting_goal", "Use a number from 0 to 50."),
    ({"weekly_meeting_goal": False}, "weekly_meeting_goal", "Use a number from 0 to 50."),
    ({"non_dsbc_website_min": 6}, "non_dsbc_website_min", "Use a number from 0 up to the meeting goal."),
    ({"non_dsbc_website_min": -1}, "non_dsbc_website_min", "Use a number from 0 up to the meeting goal."),
    ({"weekly_meeting_goal": 2, "non_dsbc_website_min": 3}, "non_dsbc_website_min",
     "Use a number from 0 up to the meeting goal."),
    ({"ai_enabled": 1}, "ai_enabled", "Use on or off."),
    ({"ai_enabled": None}, "ai_enabled", "Use on or off."),
    ({"industries": []}, "industries", PICK),
    ({"industries": ["GC", " "]}, "industries", PICK),
    ({"stages": ["Met", " met "]}, "stages", PICK),
    ({"account_types": "Utility"}, "account_types", PICK),
    ({"account_types": ["Utility", 3]}, "account_types", PICK),
    ({"lead_sources": ["DSBC Sales", "Website Lead", "dsbc sales"]}, "lead_sources", PICK),
    ({"industries": ["industry %d" % n for n in range(101)]}, "industries", PICK_SIZE),
    ({"stages": ["Met", "x" * 121]}, "stages", PICK_SIZE),
    ({"account_types": ["x" * 120] * 2}, "account_types", PICK),
])
def test_each_bad_setting_is_400_with_its_field(bd_seeded, bd_as_user, change, field, sentence):
    before = ok(bd_as_user(FRANKIE).get("/api/bd/settings"))["settings"]
    envelope(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json=change), 400, "bad_request", sentence,
             {field: sentence})
    assert ok(bd_as_user(FRANKIE).get("/api/bd/settings"))["settings"] == before


def test_good_edges_are_accepted_and_normalised(bd_seeded, bd_as_user):
    body = ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={
        "weekly": {"new_count": 10, "followup_count": 0, "run_day": "sunday", "run_hour": 0, "enabled": False,
                   "extra": "ignored"},
        "default_frequency": {"bd": 52, "maintenance": 1.0},
        "bd_cadence": "weekly",
        "weekly_meeting_goal": 0, "non_dsbc_website_min": 0, "ai_enabled": True,
        "industries": ["  Data Centers ", "GC"],
    }))
    s = body["settings"]
    assert s["weekly"] == {"new_count": 10, "followup_count": 0, "run_day": "sunday", "run_hour": 0, "enabled": False}
    assert s["default_frequency"] == {"maintenance": 1} and isinstance(s["default_frequency"]["maintenance"], int)
    assert s["bd_cadence"] == "weekly"
    assert (s["weekly_meeting_goal"], s["non_dsbc_website_min"], s["ai_enabled"]) == (0, 0, True)
    assert s["industries"] == ["Data Centers", "GC"]
    body = ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"weekly_meeting_goal": 50,
                                                                      "non_dsbc_website_min": 50}))
    assert body["settings"]["non_dsbc_website_min"] == 50


def test_read_only_and_unknown_keys_are_ignored(bd_seeded, bd_as_user, bd_db):
    before = ok(bd_as_user(FRANKIE).get("/api/bd/settings"))["settings"]
    body = ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={
        "timezone": "UTC", "maintenance_touch_days": 1, "system_lead_sources": [], "call_outcomes": ["x"],
        "interaction_kinds": [], "touch_kinds": ["email"], "favourite_colour": "blue"}))
    assert body["settings"] == before and "favourite_colour" not in body["settings"]
    assert count(bd_db, "bd.events where kind = 'settings_changed'") == 0
    assert count(bd_db, "bd.settings") == 0


def test_an_empty_put_changes_nothing(bd_seeded, bd_as_user, bd_db):
    before = ok(bd_as_user(FRANKIE).get("/api/bd/settings"))["settings"]
    assert ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={}))["settings"] == before
    assert ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings"))["settings"] == before
    assert count(bd_db, "bd.settings") == 0


def test_a_put_body_that_is_not_an_object_is_400(bd_seeded, bd_as_user):
    envelope(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json=[{"ai_enabled": True}]), 400, "bad_request",
             fields={"body": "Send a JSON object."})


def test_a_stored_bad_value_blocks_every_put_until_it_is_fixed(bd_seeded, bd_as_user, bd_db):
    """The whole result is checked: a broken stored row is reported, then fixed by sending it."""
    bd_db.execute("insert into bd.settings (key, value) values ('weekly_meeting_goal', '3'::jsonb),"
                  " ('non_dsbc_website_min', '5'::jsonb)")
    envelope(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"ai_enabled": True}), 400, "bad_request",
             fields={"non_dsbc_website_min": "Use a number from 0 up to the meeting goal."})
    ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"non_dsbc_website_min": 1}))


# ── GET /api/bd/admin/telephony ──────────────────────────────────────────────────────────────
@pytest.fixture
def phone(monkeypatch):
    def set_phone(provider="", key="", secret=""):
        monkeypatch.setattr(bd_config, "BD_TELEPHONY_PROVIDER", provider)
        monkeypatch.setattr(bd_config, "BD_QUO_API_KEY", key)
        monkeypatch.setattr(bd_config, "BD_QUO_WEBHOOK_SECRET", secret)
    set_phone()
    return set_phone


def test_telephony_with_no_provider_set(bd_seeded, bd_as_user, phone):
    assert ok(bd_as_user(FRANKIE).get("/api/bd/admin/telephony")) == {
        "ok": True, "telephony": {"provider": "null", "connected": False, "last_event_at": None,
                                  "unmatched_open": 1, "message": "No phone system connected yet."}}
    phone("null")
    assert ok(bd_as_user(FRANKIE).get("/api/bd/admin/telephony"))["telephony"]["connected"] is False


def test_telephony_counts_open_calls_only(bd_seeded, bd_as_user, bd_db, phone):
    add_unmatched(bd_db, external_id="T1")
    add_unmatched(bd_db, external_id="T2", status="dismissed")
    assert ok(bd_as_user(FRANKIE).get("/api/bd/admin/telephony"))["telephony"]["unmatched_open"] == 2
    ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/dismiss", json={}))
    assert ok(bd_as_user(FRANKIE).get("/api/bd/admin/telephony"))["telephony"]["unmatched_open"] == 1


@pytest.mark.parametrize("key,secret,connected,message", [
    ("quo-key-not-real-7f3a", "quo-secret-not-real-9c1d", True, "Quo is connected."),
    ("", "quo-secret-not-real-9c1d", False, "Quo is picked, but its API key or webhook secret is not set."),
    ("quo-key-not-real-7f3a", "", False, "Quo is picked, but its API key or webhook secret is not set."),
])
def test_telephony_with_quo_says_only_whether_its_settings_are_set(bd_seeded, bd_as_user, phone, key, secret,
                                                                    connected, message):
    phone("quo", key, secret)
    r = bd_as_user(FRANKIE).get("/api/bd/admin/telephony")
    t = ok(r)["telephony"]
    assert t == {"provider": "quo", "connected": connected, "last_event_at": None, "unmatched_open": 1,
                 "message": message}
    # Never the values themselves.
    assert "not-real" not in r.text


def test_telephony_last_event_is_the_newest_for_the_provider_in_central(bd_seeded, bd_as_user, bd_db, phone):
    phone("quo")
    # 2026-11-01 06:30 UTC is 01:30 CDT, the first pass through the fall-back hour; 07:30 UTC is 01:30 CST.
    bd_db.execute("insert into bd.integration_events (provider, event_id, received_at) values"
                  " ('quo', 'E1', '2026-11-01T06:30:00Z'), ('quo', 'E2', '2026-11-01T07:30:00Z'),"
                  " ('other', 'E3', '2026-11-04T07:30:00Z')")
    assert ok(bd_as_user(FRANKIE).get("/api/bd/admin/telephony"))["telephony"]["last_event_at"] == \
        "2026-11-01T01:30:00-06:00"
    bd_db.execute("delete from bd.integration_events where event_id = 'E2'")
    assert ok(bd_as_user(FRANKIE).get("/api/bd/admin/telephony"))["telephony"]["last_event_at"] == \
        "2026-11-01T01:30:00-05:00"


def test_an_unknown_provider_is_not_connected(bd_seeded, bd_as_user, phone):
    phone("carrierpigeon")
    t = ok(bd_as_user(FRANKIE).get("/api/bd/admin/telephony"))["telephony"]
    assert (t["provider"], t["connected"], t["message"]) == ("carrierpigeon", False,
                                                             "This phone system is not supported yet.")


# ── GET /api/bd/admin/unmatched-calls ────────────────────────────────────────────────────────
SEEDED_CALL = {"id": 801, "provider": "quo", "external_id": "QX-0002", "direction": "in",
               "from_e164": "+19135550199", "occurred_at": "2026-11-03T16:42:00-06:00", "duration_s": 95,
               "summary": "Caller asked about a quote for a shop floor.", "status": "open"}


def test_the_unmatched_calls_default_to_open(bd_seeded, bd_as_user):
    assert ok(bd_as_user(CASEY).get("/api/bd/admin/unmatched-calls")) == {"ok": True, "total": 1,
                                                                          "items": [SEEDED_CALL]}


def test_the_unmatched_calls_filter_by_status_and_page(bd_seeded, bd_as_user, bd_db):
    a = add_unmatched(bd_db, external_id="A", status="attached")
    d = add_unmatched(bd_db, external_id="D", status="dismissed")
    o = add_unmatched(bd_db, external_id="O")

    def ids(q):
        return [x["id"] for x in ok(bd_as_user(CASEY).get("/api/bd/admin/unmatched-calls" + q))["items"]]

    assert ids("") == ids("?status=open") == [801, o]
    assert ids("?status=attached") == [a]
    assert ids("?status=dismissed") == [d]
    assert ids("?status=all") == [801, a, d, o]
    page = ok(bd_as_user(CASEY).get("/api/bd/admin/unmatched-calls?status=all&limit=2&offset=1"))
    assert [x["id"] for x in page["items"]] == [a, d] and page["total"] == 4


@pytest.mark.parametrize("query,field", [("?status=closed", "status"), ("?status=", "status"),
                                         ("?offset=-1", "offset"), ("?limit=ten", "limit")])
def test_a_bad_unmatched_calls_query_is_400(bd_seeded, bd_as_user, query, field):
    body = envelope(bd_as_user(CASEY).get("/api/bd/admin/unmatched-calls" + query), 400, "bad_request")
    assert list(body["fields"]) == [field]


def test_unmatched_call_times_are_central_across_the_fall_back(bd_seeded, bd_as_user, bd_db):
    first = add_unmatched(bd_db, external_id="F1", occurred_at="2026-11-01T06:30:00Z")
    second = add_unmatched(bd_db, external_id="F2", occurred_at="2026-11-01T07:30:00Z")
    late = add_unmatched(bd_db, external_id="F3", occurred_at="2026-11-04T05:30:00Z")
    items = {x["id"]: x for x in ok(bd_as_user(CASEY).get("/api/bd/admin/unmatched-calls"))["items"]}
    assert items[first]["occurred_at"] == "2026-11-01T01:30:00-05:00"
    assert items[second]["occurred_at"] == "2026-11-01T01:30:00-06:00"
    assert items[late]["occurred_at"] == "2026-11-03T23:30:00-06:00"      # still the 3rd in Central


# ── POST /api/bd/admin/unmatched-calls/{id}/attach ───────────────────────────────────────────
ATTACH = {"contact_id": WES, "save_number": True, "outcome": "answered"}


def summary(db, contact_id):
    return db.execute("select phone, phone_e164, last_live_at, last_attempt_at, touches_this_year,"
                      " attempts_since_live, cadence_status from bd.contacts_summary where id = %s",
                      (contact_id,)).fetchone()


def test_attaching_puts_the_call_on_the_contact_and_saves_the_number(bd_seeded, bd_as_user, bd_db, phone):
    before = summary(bd_db, WES)
    assert (before["phone"], before["touches_this_year"]) == ("913-555-0112", 0)
    body = ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json=ATTACH))
    assert body["unmatched_call"] == {"id": 801, "status": "attached"}
    i = body["interaction"]
    assert {k: v for k, v in i.items() if k not in ("id", "contact")} == {
        "contact_id": WES, "kind": "call", "direction": "in", "counts_as_touch": True,
        "occurred_at": "2026-11-03T16:42:00-06:00", "duration_s": 95, "outcome": "answered",
        "summary": "Caller asked about a quote for a shop floor.", "transcript": None, "recording_url": None,
        "provider": "quo", "external_id": "QX-0002", "user": None}
    assert i["contact"] == {"id": WES, "name": "Wes Calder", "company": {"id": 18, "name": "Osage Plains Brewing"}}
    after = summary(bd_db, WES)
    assert (after["phone"], after["phone_e164"]) == ("913-555-0199", "+19135550199")
    assert (after["touches_this_year"], after["attempts_since_live"]) == (1, 0)
    assert serialize.ts(after["last_live_at"]) == "2026-11-03T16:42:00-06:00"
    row = bd_db.execute("select status, attached_interaction_id, handled_by, handled_at from bd.unmatched_calls"
                        " where id = 801").fetchone()
    assert (row["status"], row["attached_interaction_id"], row["handled_by"]) == ("attached", i["id"], CASEY)
    assert row["handled_at"] is not None
    # Gone from the open queue, listed under attached.
    assert ok(bd_as_user(CASEY).get("/api/bd/admin/unmatched-calls"))["total"] == 0
    assert ok(bd_as_user(CASEY).get("/api/bd/admin/unmatched-calls?status=attached"))["items"] == [
        dict(SEEDED_CALL, status="attached")]
    assert ok(bd_as_user(FRANKIE).get("/api/bd/admin/telephony"))["telephony"]["unmatched_open"] == 0


def test_attaching_closes_a_maintenance_task_the_call_cleared(bd_seeded, bd_as_user, bd_db):
    """The attach never closes a new or follow-up task (close_task False), but a call that clears a due
    maintenance contact must not leave its pinned task open: it closes with the follow-up (this week's
    and a later week's). Nora Lindqvist (31) is a maintenance contact never followed up (due)."""
    this_week = bd_db.execute("insert into bd.tasks (batch_id, contact_id, kind) values (201, 31, 'maintenance')"
                              " returning id").fetchone()["id"]
    b = bd_db.execute("insert into bd.task_batches (owner_id, week_start, kind) values (1, '2026-11-09', 'friday')"
                      " returning id").fetchone()["id"]
    nxt = bd_db.execute("insert into bd.tasks (batch_id, contact_id, kind) values (%s, 31, 'maintenance') returning id",
                        (b,)).fetchone()["id"]
    assert bd_db.execute("select maintenance_due from bd.contacts_summary where id = 31").fetchone()["maintenance_due"]
    cid = add_unmatched(bd_db, external_id="M1", from_e164="+17855550177", duration_s=95)
    ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/%d/attach" % cid, json={"contact_id": 31,
                                                                                    "outcome": "answered"}))

    def status(t):
        return bd_db.execute("select status from bd.tasks where id = %s", (t,)).fetchone()["status"]

    assert (status(this_week), status(nxt)) == ("done", "done")
    assert bd_db.execute("select maintenance_due from bd.contacts_summary where id = 31").fetchone()["maintenance_due"] \
        is False
    # An attach to a BD contact leaves its task open: Dana Whitlow (21), task 302.
    cid2 = add_unmatched(bd_db, external_id="M2", from_e164="+19135550178", duration_s=95)
    ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/%d/attach" % cid2, json={"contact_id": 21,
                                                                                     "outcome": "answered"}))
    assert status(302) == "open"


def test_attaching_twice_is_409(bd_seeded, bd_as_user, bd_db):
    ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json=ATTACH))
    envelope(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json={"contact_id": WES}),
             409, "conflict", "That call was already handled.")
    assert count(bd_db, "bd.interactions where external_id = 'QX-0002'") == 1


@pytest.mark.parametrize("duration,outcome,touch", [
    (95, "answered", True), (60, "answered", True), (59, "no_answer", False),
    (40, "no_answer", False), (0, "no_answer", False), (None, "no_answer", False),
])
def test_without_an_outcome_only_a_minute_or_more_counts(bd_seeded, bd_as_user, bd_db, duration, outcome, touch):
    cid = add_unmatched(bd_db, external_id="DUR", duration_s=duration)
    i = ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/%d/attach" % cid,
                                  json={"contact_id": WES}))["interaction"]
    assert (i["kind"], i["outcome"], i["counts_as_touch"], i["duration_s"]) == ("call", outcome, touch, duration)
    # save_number defaults to false: the contact keeps its number.
    assert summary(bd_db, WES)["phone"] == "913-555-0112"


@pytest.mark.parametrize("said,kind,touch", [("answered", "call", True), ("no_answer", "call", False),
                                             ("voicemail", "voicemail", False)])
def test_with_the_assistants_outcome(bd_seeded, bd_as_user, bd_db, said, kind, touch):
    cid = add_unmatched(bd_db, external_id="SAID", duration_s=40)
    i = ok(bd_as_user(FRANKIE).post("/api/bd/admin/unmatched-calls/%d/attach" % cid,
                                    json={"contact_id": WES, "outcome": said, "save_number": False}))["interaction"]
    assert (i["kind"], i["outcome"], i["counts_as_touch"]) == (kind, said, touch)
    row = bd_db.execute("select kind, outcome, counts_as_touch, user_id from bd.interactions where id = %s",
                        (i["id"],)).fetchone()
    assert (row["kind"], row["outcome"], row["counts_as_touch"], row["user_id"]) == (kind, said, touch, None)


def test_a_short_call_with_no_outcome_is_no_answer(bd_seeded, bd_as_user, bd_db):
    """A 40-second call, no outcome: no_answer, never a live talk (it may have been a voicemail)."""
    bd_db.execute("update bd.unmatched_calls set duration_s = 40 where id = 801")
    got = ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json={"contact_id": WES}))
    assert (got["interaction"]["outcome"], got["interaction"]["counts_as_touch"]) == ("no_answer", False)
    assert summary(bd_db, WES)["touches_this_year"] == 0


def test_attaching_a_text_keeps_no_outcome(bd_seeded, bd_as_user, bd_db):
    cid = add_unmatched(bd_db, external_id="SMS1", kind="sms", duration_s=None, summary="Can you send the quote?")
    i = ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/%d/attach" % cid,
                                  json={"contact_id": WES, "outcome": "answered"}))["interaction"]
    assert (i["kind"], i["outcome"], i["counts_as_touch"], i["summary"]) == ("sms", None, False,
                                                                             "Can you send the quote?")


def test_attaching_copies_the_transcript_and_recording(bd_seeded, bd_as_user, bd_db):
    cid = add_unmatched(bd_db, external_id="TR1", duration_s=120, transcript="Hello.",
                        recording_url="https://example.com/r/1")
    i = ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/%d/attach" % cid,
                                  json={"contact_id": WES}))["interaction"]
    assert (i["transcript"], i["recording_url"]) == ("Hello.", "https://example.com/r/1")


def test_save_number_with_no_usable_number_keeps_the_phone(bd_seeded, bd_as_user, bd_db):
    cid = add_unmatched(bd_db, external_id="NONUM", from_e164=None)
    ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/%d/attach" % cid,
                              json={"contact_id": WES, "save_number": True}))
    assert summary(bd_db, WES)["phone"] == "913-555-0112"


@pytest.mark.parametrize("payload,message,fields", [
    ({}, "Pick a contact.", {"contact_id": "Pick a contact."}),
    ({"contact_id": "32"}, "Pick a contact.", {"contact_id": "Pick a contact."}),
    ({"contact_id": True}, "Pick a contact.", {"contact_id": "Pick a contact."}),
    ({"contact_id": 32.5}, "Pick a contact.", {"contact_id": "Pick a contact."}),
    ({"contact_id": 32, "outcome": "meeting_set"}, "Pick how the call went.",
     {"outcome": "Use answered, voicemail or no_answer."}),
    ({"contact_id": 32, "outcome": "Answered"}, "Pick how the call went.",
     {"outcome": "Use answered, voicemail or no_answer."}),
    ({"contact_id": 32, "save_number": "yes"}, "Use true or false.", {"save_number": "Use true or false."}),
    ({"outcome": "maybe"}, "Some fields need fixing.",
     {"contact_id": "Pick a contact.", "outcome": "Use answered, voicemail or no_answer."}),
])
def test_a_bad_attach_is_400_and_leaves_the_call_open(bd_seeded, bd_as_user, bd_db, payload, message, fields):
    envelope(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json=payload), 400, "bad_request",
             message, fields)
    assert bd_db.execute("select status from bd.unmatched_calls where id = 801").fetchone()["status"] == "open"
    assert count(bd_db, "bd.interactions where external_id = 'QX-0002'") == 0


@pytest.mark.parametrize("contact_id", [999, 0, -3, 2 ** 70])
def test_attaching_to_an_unknown_contact_is_404(bd_seeded, bd_as_user, bd_db, contact_id):
    envelope(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json={"contact_id": contact_id}),
             404, "not_found", "That contact does not exist.")
    assert bd_db.execute("select status from bd.unmatched_calls where id = 801").fetchone()["status"] == "open"


@pytest.mark.parametrize("path", ["/api/bd/admin/unmatched-calls/999/attach", "/api/bd/admin/unmatched-calls/999/dismiss",
                                  "/api/bd/admin/unmatched-calls/99999999999999999999/attach",
                                  "/api/bd/admin/unmatched-calls/abc/dismiss",
                                  "/api/bd/admin/unmatched-calls/%20801/attach"])
def test_an_unknown_call_is_404(bd_seeded, bd_as_user, path):
    envelope(bd_as_user(CASEY).post(path, json={"contact_id": WES}), 404, "not_found", "That call does not exist.")


def test_attaching_a_dismissed_call_is_409(bd_seeded, bd_as_user):
    ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/dismiss", json={}))
    envelope(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json=ATTACH), 409, "conflict",
             "That call was already handled.")


def test_a_call_already_on_a_timeline_is_409_and_changes_nothing(bd_seeded, bd_as_user, bd_db):
    """The webhook may have matched the same provider call meanwhile (unique provider + external_id)."""
    bd_db.execute("insert into bd.interactions (contact_id, kind, outcome, occurred_at, provider, external_id)"
                  " values (21, 'call', 'answered', '2026-11-03T16:42:00-06:00', 'quo', 'QX-0002')")
    envelope(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json=ATTACH), 409, "conflict",
             "That call is already on a contact's timeline.")
    assert bd_db.execute("select status from bd.unmatched_calls where id = 801").fetchone()["status"] == "open"
    assert summary(bd_db, WES)["phone"] == "913-555-0112"


def test_an_attach_body_that_is_not_an_object_is_400(bd_seeded, bd_as_user):
    envelope(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json=[32]), 400, "bad_request",
             fields={"body": "Send a JSON object."})


def test_an_attached_call_after_today_does_not_count_yet(bd_seeded, bd_as_user, bd_db, bd_today):
    """Derived fields read only interactions up to Central today (bd_today())."""
    cid = add_unmatched(bd_db, external_id="FUT", duration_s=300, occurred_at="2026-11-05T06:30:00Z")  # 00:30 CST on the 5th
    ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/%d/attach" % cid, json={"contact_id": WES}))
    assert summary(bd_db, WES)["touches_this_year"] == 0
    bd_today("2026-11-05")
    assert summary(bd_db, WES)["touches_this_year"] == 1


def test_attaching_neither_closes_the_weekly_task_nor_suggests_a_next_step(bd_seeded, bd_as_user, bd_db):
    """The call goes on the timeline; the week and the suggestion queue are untouched. Dana Whitlow (21)
    has the open follow-up task 302."""
    tasks = bd_db.execute("select id, status, done_at from bd.tasks order by id").fetchall()
    recs = count(bd_db, "bd.ai_recommendations")
    ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json={"contact_id": 21, "outcome": "answered"}))
    assert bd_db.execute("select id, status, done_at from bd.tasks order by id").fetchall() == tasks
    assert count(bd_db, "bd.ai_recommendations") == recs


def test_an_answered_attach_meets_a_kept_promise(bd_seeded, bd_as_user, bd_db):
    """A live call on or after promised_date clears it, with the next step."""
    bd_db.execute("update bd.contacts set promised_date = '2026-11-03', next_step = 'Call back',"
                  " next_step_date = '2026-11-03' where id = %s", (WES,))
    ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json={"contact_id": WES, "outcome": "answered"}))
    row = bd_db.execute("select promised_date, next_step, next_step_date from bd.contacts where id = %s",
                        (WES,)).fetchone()
    assert (row["promised_date"], row["next_step"], row["next_step_date"]) == (None, None, None)


def test_a_missed_attach_keeps_the_promise(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("update bd.contacts set promised_date = '2026-11-03' where id = %s", (WES,))
    ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/attach", json={"contact_id": WES,
                                                                               "outcome": "voicemail"}))
    assert str(bd_db.execute("select promised_date from bd.contacts where id = %s", (WES,)).fetchone()
               ["promised_date"]) == "2026-11-03"


# ── POST /api/bd/admin/unmatched-calls/{id}/dismiss ──────────────────────────────────────────
def test_dismissing_and_twice_is_409(bd_seeded, bd_as_user, bd_db):
    assert ok(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/dismiss", json={})) == {
        "ok": True, "unmatched_call": {"id": 801, "status": "dismissed"}}
    envelope(bd_as_user(CASEY).post("/api/bd/admin/unmatched-calls/801/dismiss", json={}), 409, "conflict",
             "That call was already handled.")
    row = bd_db.execute("select status, handled_by, handled_at, attached_interaction_id from bd.unmatched_calls"
                        " where id = 801").fetchone()
    assert (row["status"], row["handled_by"], row["attached_interaction_id"]) == ("dismissed", CASEY, None)
    assert row["handled_at"] is not None
    assert count(bd_db, "bd.interactions where external_id = 'QX-0002'") == 0


def test_dismissing_an_attached_call_is_409(bd_seeded, bd_as_user):
    ok(bd_as_user(FRANKIE).post("/api/bd/admin/unmatched-calls/801/attach", json=ATTACH))
    envelope(bd_as_user(FRANKIE).post("/api/bd/admin/unmatched-calls/801/dismiss", json={}), 409, "conflict",
             "That call was already handled.")


def test_reads_never_write_the_settings(bd_seeded, bd_as_user, bd_db):
    """GET /api/bd/settings and the admin GETs never write."""
    ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings", json={"bd_cadence": "monthly"}))
    snap = copy.deepcopy(bd_db.execute("select key, value, updated_at from bd.settings order by key").fetchall())
    for path in ("/api/bd/settings", "/api/bd/admin/users", "/api/bd/admin/telephony"):
        ok(bd_as_user(FRANKIE).get(path))
    assert bd_db.execute("select key, value, updated_at from bd.settings order by key").fetchall() == snap


# ── a settings change moves the Friday batch (#809) ──────────────────────────────────────────
# The fixture seed's week is Mon 2 Nov 2026; the Friday batch builds the week of Mon 9 Nov for each
# active salesperson (Avery 1, Blair 2). Fri 6, Sat 7 Nov are CST (UTC-6). The worker's due check is
# weekly_worker.Worker.tick -> weekly.run_due, with the business clock pinned.
@pytest.fixture
def worker_on(monkeypatch, bd_today):
    from bd import weekly_worker

    monkeypatch.setattr(bd_config, "BD_WEEKLY_ENABLED", True)

    def tick_at(moment):
        monkeypatch.setenv("BD_NOW", moment)
        bd_today(None)
        w = weekly_worker.Worker(interval=60, clock=lambda: moment)
        built = w.tick()
        assert w.failures == 0
        return [(b["owner_id"], str(b["week_start"])) for b in built]

    yield tick_at
    monkeypatch.delenv("BD_NOW", raising=False)


def test_moving_the_run_day_and_hour_moves_when_the_batch_is_due(bd_seeded, bd_as_user, worker_on):
    ok(bd_as_user(FRANKIE).put("/api/bd/admin/settings",
                               json={"weekly": {"run_day": "saturday", "run_hour": 9, "enabled": True}}))
    assert worker_on("2026-11-06T16:00:00-06:00") == []          # Friday 16:00, the old moment
    assert worker_on("2026-11-07T08:59:59-06:00") == []          # Saturday, a second before 9
    assert worker_on("2026-11-07T09:00:00-06:00") == [(AVERY, "2026-11-09"), (BLAIR, "2026-11-09")]


def test_moving_only_the_hour_moves_when_the_batch_is_due(bd_seeded, bd_as_user, worker_on):
    ok(bd_as_user(EMERY).put("/api/bd/admin/settings", json={"weekly": {"run_hour": 18, "enabled": True}}))
    assert worker_on("2026-11-06T16:00:00-06:00") == []
    assert worker_on("2026-11-06T17:59:59-06:00") == []
    assert worker_on("2026-11-06T18:00:00-06:00") == [(AVERY, "2026-11-09"), (BLAIR, "2026-11-09")]


def test_the_default_moment_is_friday_at_16_and_off_in_settings_builds_nothing(bd_seeded, bd_as_user, worker_on):
    ok(bd_as_user(EMERY).put("/api/bd/admin/settings", json={"weekly": {"enabled": False}}))
    assert worker_on("2026-11-06T16:00:00-06:00") == []
    ok(bd_as_user(EMERY).put("/api/bd/admin/settings", json={"weekly": {"enabled": True}}))
    assert worker_on("2026-11-06T15:59:59-06:00") == []
    assert worker_on("2026-11-06T16:00:00-06:00") == [(AVERY, "2026-11-09"), (BLAIR, "2026-11-09")]


def test_a_refused_settings_change_leaves_the_batch_where_it_was(bd_seeded, bd_as_user, worker_on):
    ok(bd_as_user(EMERY).put("/api/bd/admin/settings", json={"weekly": {"enabled": True}}))
    envelope(bd_as_user(EMERY).put("/api/bd/admin/settings", json={"weekly": {"run_day": "monday"}}), 400,
             "bad_request")
    envelope(bd_as_user(DEVON).put("/api/bd/admin/settings", json={"weekly": {"run_day": "sunday"}}), 403,
             "forbidden")
    assert worker_on("2026-11-06T16:00:00-06:00") == [(AVERY, "2026-11-09"), (BLAIR, "2026-11-09")]
