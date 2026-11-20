"""Who may call what under /api/bd/: the role matrix (#809, BD's test_authz_matrix moved onto the tool).

  A. CLASSIFICATION. Every /api/bd/ route the app registers is written down once, in
     tests/_bd_routes.py (ROUTE_ROLES, or WEBHOOK). A route with no line fails with a pointer to
     docs/bd/api-contract.md, and so does a line for a route that is gone; the role words of the
     contract's heading and the table must say the same thing; bd/routers/pending.py lets in the same
     roles; and the tool's gate (main._auth_is_public) opens exactly the webhook.
  B. THE DOORS IN FRONT OF EVERY ROUTE, route by route: the BD switch off is 503 "not turned on"; no
     sign-in is the tool's 401; a signed-in staffer with no BD login is 403 "You don't have a BD
     role."; a turned-off BD login is 403 "Your BD login is turned off.".
  C. ROLE x ROUTE. Every route is called as every BD role on the fixture seed (bd/ops/fixture_seed.py),
     one person each:

         salesperson  Avery (1)     assistant  Casey (3)     manager  Devon (4)
         admin        Emery (5)     super admin  Frankie (6)

     A role the table does not list is 403 with BD's envelope; a role it lists gets past the role check
     (NOT 401/403: 400/404/409 are fine, this is the door, not the handler), a read with nothing to set
     up answers 200, and a route not built yet answers 503 "not built yet" behind its door.
  D. THE RULES BEHIND THE DOOR that BD's matrix held and no other BD test file holds: someone else's
     week or list however its id is spelled, a contact shared by the whole team, server-owned keys in a
     body (archived_at / archived on a contact PATCH among them), and a manager's cadence-only edit,
     key by key.

Every BD matrix test that is not here under its own name is in the #809 PR's "Not carried over /
renamed" table, with the test that covers it now. The service-token route and its checks were not
carried (#806); BD's own token checks are the tool's sign-in now (test_bd_token_tampering.py).
"""
from __future__ import annotations

import io

import pytest

import main
from _bd_conftest import bd_token_headers
from _bd_routes import (
    ALL_ROLES,
    OWNERSHIP_GATED,
    ROLES,
    ROUTE_ROLES,
    WEBHOOK,
    _open,
    classify,
    concrete,
    documented,
    documented_who,
    heading_roles,
    real_routes,
    unclassified,
)
from bd import auth as bd_auth
from bd import config as bd_config
from bd.routers import pending

UID = {"salesperson": 1, "assistant": 3, "manager": 4, "admin": 5, "super_admin": 6}
BLAIR = 2                         # the other salesperson
GALE = 7                          # the seed's turned-off salesperson
STAFFER = "new.hire@example.com"  # signed in to the tool, no BD login

SHARED_CONTACT = 21               # Dana Whitlow, Avery's: read, patched with {}, a note logged on
THROWAWAY_CONTACT = 33            # D. Whitlow: confirmed / archived by the door checks
COMPANY = 10
UNMATCHED_CALL = 801
CANDIDATE = 601
RECOMMENDATION = 401
AVERYS_ENTRY = 101                # Avery logged it
DELETE_TARGET = 102
CSV = b"Company,Name,Email\nTallgrass Dental,Rae Lindgren,rae.lindgren@tallgrass.example.com\n"
UPLOAD = ("POST", "/api/bd/admin/import")

ROUTE_KEYS = sorted(ROUTE_ROLES)
DOCS = documented()
DOC_WHO = documented_who()
NOT_TURNED_ON = {"ok": False, "error": "unavailable", "message": "The BD CRM is not turned on."}
YOUR_ROLE = "Your role can't do that."


def key_id(key):
    return "%s %s" % key


def forbidden(message=YOUR_ROLE):
    return {"ok": False, "error": "forbidden", "message": message}


# ══ A. CLASSIFICATION ════════════════════════════════════════════════════════════════════════════
def test_every_registered_bd_route_is_classified_exactly_once():
    missing = unclassified(real_routes())
    assert not missing, (
        "These /api/bd/ routes have no door written down: %r. Document each in docs/bd/api-contract.md "
        "(its heading names who may call it), then add ONE line for it in tests/_bd_routes.py: "
        "ROUTE_ROLES with its roles, or WEBHOOK if it takes no sign-in." % (missing,))
    twice = sorted(k for k in real_routes() if "+" in (classify(*k) or ""))
    assert not twice, "routes classified in more than one table: %r" % (twice,)


def test_the_self_check_names_a_route_with_no_row():
    """A new route with no line is found by name: the check above cannot pass by finding nothing."""
    new = ("POST", "/api/bd/contacts/{id}/new-thing")
    assert unclassified(real_routes() | {new}) == [new]
    assert unclassified({("GET", "/api/bd/me"), ("POST", "/api/bd/webhooks/telephony/quo")}) == []


def test_no_stale_line_in_the_route_tables():
    stale = sorted((set(ROUTE_ROLES) | WEBHOOK) - real_routes())
    assert not stale, "tests/_bd_routes.py lists routes the app no longer serves: %r (delete the lines)" % (stale,)


def test_the_route_tables_are_well_formed():
    assert len(ROUTE_ROLES) == len(real_routes()) - len(WEBHOOK) >= 45
    for key, roles in ROUTE_ROLES.items():
        assert roles <= ALL_ROLES, key
        assert {"admin", "super_admin"} <= roles, "%s: an admin passes every role check" % (key,)


@pytest.mark.parametrize("method,path", DOCS, ids=[key_id(k) for k in DOCS])
def test_the_contract_heading_and_the_table_say_the_same_thing(method, path):
    who = DOC_WHO[(method, path)]
    kind = heading_roles(who)
    key = (method, path)
    if kind[0] == "roles":
        assert key in ROUTE_ROLES, "%s %s: heading says %r, but tests/_bd_routes.py has no ROUTE_ROLES line" % (
            method, path, who)
        assert ROUTE_ROLES[key] == kind[1], "%s %s: heading says %r -> %s, ROUTE_ROLES says %s" % (
            method, path, who, sorted(kind[1]), sorted(ROUTE_ROLES[key]))
        assert key not in OWNERSHIP_GATED
    elif kind[0] == "person":
        assert key in OWNERSHIP_GATED, "%s %s: heading names a person, so list it in OWNERSHIP_GATED" % key
        assert ROUTE_ROLES[key] == ALL_ROLES
    else:
        assert key in WEBHOOK, "%s %s is public in the contract but not in WEBHOOK" % key
        assert "signature" in who


def test_the_heading_reader():
    assert heading_roles("any BD role") == ("roles", ALL_ROLES)
    assert heading_roles("salesperson; an assistant logs notes only") == ("roles", _open("salesperson", "assistant"))
    assert heading_roles("admin; a super admin to add an admin") == ("roles", _open())
    assert heading_roles("manager; not built yet") == ("roles", _open("manager"))
    assert heading_roles("whoever logged it; admin") == ("person",)
    assert heading_roles("public: the provider's signature, once built; not built yet") == ("public",)
    with pytest.raises(ValueError):
        heading_roles("everyone")


def test_the_pending_placeholders_open_the_same_doors_as_the_table():
    for (method, path), who in pending.ACCESS.items():
        if who == pending.PUBLIC:
            assert (method, path) in WEBHOOK
        else:
            assert ROUTE_ROLES[(method, path)] == _open(*who), (
                "%s %s: bd/routers/pending.py lets %r in, tests/_bd_routes.py says %s" % (
                    method, path, who, sorted(ROUTE_ROLES[(method, path)])))


def test_the_gate_opens_exactly_the_webhook():
    """main._auth_is_public (the tool's list of doors with no sign-in), for every /api/bd/ route."""
    for method, path in sorted(real_routes()):
        assert main._auth_is_public(concrete(path), method) == ((method, path) in WEBHOOK), (method, path)


# ══ B. THE DOORS IN FRONT OF EVERY ROUTE ═════════════════════════════════════════════════════════
def request_for(bd_db, method, template, role):
    """(url, kwargs) of a request this route lets through its role check when `role` is let in: real
    ids where the handler looks the row up, and a body that needs no work or fails validation AFTER
    the role check (so the check is the door, not the handler)."""
    if template.startswith("/api/bd/tasks/"):
        url = template.replace("{id}", "303" if template.endswith("/reopen") else "302")
    elif template in ("/api/bd/contacts/{id}/archive", "/api/bd/contacts/{id}/confirm",
                      "/api/bd/contacts/{id}/merge"):
        url = template.replace("{id}", str(THROWAWAY_CONTACT))
    elif template.startswith("/api/bd/contacts/{id}"):
        url = template.replace("{id}", str(SHARED_CONTACT))
    elif template == "/api/bd/interactions/{id}":
        if method == "PATCH":                      # whoever logged it: the caller's own entry
            own = bd_db.execute(
                "insert into bd.interactions (contact_id, user_id, kind, occurred_at, summary)"
                " values (%s, %s, 'note', bd_now(), 'a note of its own') returning id",
                (SHARED_CONTACT, UID[role])).fetchone()["id"]
            url = template.replace("{id}", str(own))
        else:
            url = template.replace("{id}", str(DELETE_TARGET))
    elif template.startswith("/api/bd/interactions/{id}/"):
        url = template.replace("{id}", str(AVERYS_ENTRY))
    elif template.startswith("/api/bd/companies/"):
        url = template.replace("{id}", str(COMPANY))
    elif template.startswith("/api/bd/admin/users/"):
        url = template.replace("{id}", str(BLAIR))
    elif template.startswith("/api/bd/admin/unmatched-calls/"):
        url = template.replace("{id}", str(UNMATCHED_CALL))
    elif template.startswith("/api/bd/review/candidates/"):
        url = template.replace("{id}", str(CANDIDATE))
    elif template.startswith("/api/bd/recommendations/"):
        url = template.replace("{id}", str(RECOMMENDATION))
    else:
        url = concrete(template)
    if (method, template) == UPLOAD:
        return url, {"files": {"file": ("people.csv", io.BytesIO(CSV), "text/csv")}, "data": {"dry_run": "true"}}
    if method in ("GET", "DELETE"):
        return url, {}
    body = {}
    if (method, template) == ("POST", "/api/bd/contacts/{id}/interactions"):
        body = {"kind": "note", "summary": "gate check"}                  # an assistant may log notes
    elif (method, template) == ("POST", "/api/bd/admin/weekly/run"):
        body = {"week_start": "not-a-date"}                               # 400 after the role check
    elif (method, template) == ("POST", "/api/bd/admin/unmatched-calls/{id}/attach"):
        body = {"contact_id": 32, "outcome": "answered"}
    return url, {"json": body}


@pytest.mark.parametrize("method,path", ROUTE_KEYS, ids=[key_id(k) for k in ROUTE_KEYS])
def test_every_route_has_the_four_doors(bd_seeded, bd_client, bd_db, monkeypatch, real_verify_identity,
                                        method, path):
    import supabase_client

    url, kw = request_for(bd_db, method, path, "super_admin")
    # A signed-in staffer with no BD login, and a turned-off BD login: 403, BD's words.
    r = bd_client.request(method, url, headers=bd_token_headers(STAFFER), **kw)
    assert (r.status_code, r.json()) == (403, forbidden(bd_auth.NO_BD_ROLE)), r.text
    url, kw = request_for(bd_db, method, path, "super_admin")
    r = bd_client.request(method, url, headers=bd_token_headers("gale.ward@example.com"), **kw)
    assert (r.status_code, r.json()) == (403, forbidden(bd_auth.TURNED_OFF)), r.text
    assert bd_db.execute("select count(*) as n from bd.users where email = %s", (STAFFER,)).fetchone()["n"] == 0
    # The switch off: 503 "not turned on", even for the super admin.
    monkeypatch.setattr(bd_config, "BD_ENABLED", False)
    url, kw = request_for(bd_db, method, path, "super_admin")
    r = bd_client.request(method, url, headers=bd_token_headers("frankie.oduya@example.com"), **kw)
    assert (r.status_code, r.json()) == (503, NOT_TURNED_ON), r.text
    # No sign-in, switch on: the tool's gate, in the tool's shape, through the real verify step.
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    monkeypatch.setattr(supabase_client, "verify_identity", real_verify_identity)
    url, kw = request_for(bd_db, method, path, "super_admin")
    r = bd_client.request(method, url, **kw)
    body = r.json()
    assert r.status_code == 401 and set(body) == {"ok", "error"} and body["ok"] is False, r.text


def test_the_webhook_takes_no_sign_in_and_is_not_built(bd_seeded, bd_client, monkeypatch, real_verify_identity):
    import supabase_client

    monkeypatch.setattr(supabase_client, "verify_identity", real_verify_identity)
    for method, path in sorted(WEBHOOK):
        r = bd_client.request(method, path, json={"type": "call.completed"})
        assert r.status_code == 503 and r.json()["error"] == "unavailable", r.text
        assert "not built yet" in r.json()["message"]
    monkeypatch.setattr(bd_config, "BD_ENABLED", False)
    for method, path in sorted(WEBHOOK):
        assert bd_client.request(method, path, json={}).json() == NOT_TURNED_ON


@pytest.mark.parametrize("path", [
    "/api/bd/me/", "/api/bd//me", "/api/bd/./me", "/API/bd/me", "/api/BD/me", "/api/bd/me%20", "/api/bd/%6De",
    "/api/bd/me;x=1", "/api/bd/me/.", "/api/bd/me%00", "/api/bd/webhooks/telephony/quo/../../me",
    "/api/bd/webhooks/telephony/quo%2F..%2F..%2Fme", "/api/bd/webhooks/telephony/../../me", "/api/bd", "/api/bd/",
], ids=lambda p: p)
def test_path_tricks_do_not_open_a_door_without_a_sign_in(bd_seeded, bd_client, monkeypatch, real_verify_identity,
                                                          path):
    """BD's path tricks, under /api/bd/: a doubled or dotted slash, another case, an encoded letter or
    slash, a parameter or a NUL, a walk out of the public webhook. None of them reaches a BD answer
    without a sign-in."""
    import supabase_client

    monkeypatch.setattr(supabase_client, "verify_identity", real_verify_identity)
    r = bd_client.get(path)
    assert r.status_code in (400, 401, 404), (path, r.status_code, r.text[:200])
    assert "avery" not in r.text.lower() and '"user"' not in r.text, (path, r.text[:200])


def test_options_and_head_without_a_sign_in_give_nothing(bd_seeded, bd_client, monkeypatch, real_verify_identity):
    import supabase_client

    monkeypatch.setattr(supabase_client, "verify_identity", real_verify_identity)
    r = bd_client.options("/api/bd/me")
    assert r.status_code in (200, 400, 401, 404, 405) and '"user"' not in r.text, (r.status_code, r.text)
    assert "access-control-allow-origin" not in r.headers
    r = bd_client.head("/api/bd/me")
    assert r.status_code == 401 and r.content == b"", (r.status_code, r.content[:200])


# ══ C. ROLE x ROUTE ══════════════════════════════════════════════════════════════════════════════
GATE_CASES = [(m, p, role) for (m, p) in ROUTE_KEYS for role in ROLES]

# Reads that need no setup: where the door lets a role in, it must lead to a 200, not just "not
# 401/403" (a handler answering 404 to everybody would otherwise pass for a route open to all).
ALWAYS_200 = {("GET", p) for p in (
    "/api/bd/me", "/api/bd/settings", "/api/bd/users", "/api/bd/week", "/api/bd/contacts",
    "/api/bd/contacts/duplicates", "/api/bd/contacts/{id}", "/api/bd/contacts/{id}/interactions",
    "/api/bd/companies", "/api/bd/companies/{id}", "/api/bd/admin/users", "/api/bd/admin/telephony",
    "/api/bd/admin/unmatched-calls", "/api/bd/admin/imports")}

# A refusal in the route's own words (BD's), where it is not "Your role can't do that.".
REFUSALS = {("GET", "/api/bd/week", "assistant"): "The weekly list is the salesperson's."}


@pytest.mark.parametrize("method,path,role", GATE_CASES, ids=["%s %s as %s" % c for c in GATE_CASES])
def test_a_role_gets_through_exactly_the_doors_the_table_lists(bd_seeded, bd_db, bd_as_user, method, path, role):
    url, kw = request_for(bd_db, method, path, role)
    r = bd_as_user(UID[role]).request(method, url, **kw)
    if role not in ROUTE_ROLES[(method, path)]:
        assert (r.status_code, r.json()) == (403, forbidden(REFUSALS.get((method, path, role), YOUR_ROLE))), r.text
        return
    assert r.status_code not in (401, 403), "%s %s as %s was refused: %s %s" % (
        method, path, role, r.status_code, r.text[:200])
    if (method, path) in pending.PENDING:
        assert r.status_code == 503 and r.json()["error"] == "unavailable" and \
            "not built yet" in r.json()["message"], r.text
    elif (method, path) in ALWAYS_200:
        assert r.status_code == 200, (method, path, role, r.status_code, r.text[:200])
    else:
        assert r.status_code < 500, (method, path, role, r.status_code, r.text[:200])


def test_an_entry_is_changed_only_by_whoever_logged_it_or_an_admin(bd_seeded, bd_db, bd_as_user):
    """The one ownership door (OWNERSHIP_GATED): Avery's entry 101."""
    url = "/api/bd/interactions/%d" % AVERYS_ENTRY
    before = bd_db.execute("select * from bd.interactions where id = %s", (AVERYS_ENTRY,)).fetchone()
    for uid in (BLAIR, UID["assistant"], UID["manager"]):
        r = bd_as_user(uid).patch(url, json={"summary": "tampered"})
        assert (r.status_code, r.json()) == (403, forbidden("Only the person who logged this can change it."))
    assert bd_db.execute("select * from bd.interactions where id = %s", (AVERYS_ENTRY,)).fetchone() == before
    assert bd_as_user(1).patch(url, json={"summary": "Avery edits her own call"}).status_code == 200
    for role in ("admin", "super_admin"):
        r = bd_as_user(UID[role]).patch(url, json={"summary": "an admin edits it (%s)" % role})
        assert r.status_code == 200 and r.json()["interaction"]["user"]["id"] == 1, "an admin's edit keeps the author"


# ══ D. THE RULES BEHIND THE DOOR ═════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("owner", ["2", " 2 ", "02"], ids=["text", "padded", "zero-padded"])
def test_a_salesperson_sees_only_their_own_week_however_the_id_is_spelled(bd_seeded, bd_as_user, owner):
    r = bd_as_user(1).get("/api/bd/week", params={"owner": owner})
    assert (r.status_code, r.json()) == (403, forbidden("You can see only your own week."))


@pytest.mark.parametrize("owner", ["3", "4", "999999", "1.0", "1e0", "true", "[1]", "-1", "abc", "2.0"])
def test_an_odd_or_non_salesperson_owner_is_never_someones_week(bd_seeded, bd_as_user, owner):
    r = bd_as_user(1).get("/api/bd/week", params={"owner": owner})
    assert r.status_code in (403, 404), (owner, r.status_code, r.text[:200])


@pytest.mark.parametrize("owner", [2, 2.0, "2", " 2 ", "02"], ids=["int", "float", "text", "padded", "zero-padded"])
def test_ten_more_cannot_be_asked_on_someone_elses_list(bd_seeded, bd_db, bd_as_user, owner):
    """Avery names Blair's list, however it is spelled: 403, and nothing is built on Blair's list."""
    batches = bd_db.execute("select count(*) as n from bd.task_batches").fetchone()["n"]
    r = bd_as_user(1).post("/api/bd/week/ten-more", json={"owner": owner})
    assert (r.status_code, r.json()) == (403, forbidden("You can ask for more only on your own list."))
    assert bd_db.execute("select count(*) as n from bd.task_batches").fetchone()["n"] == batches


@pytest.mark.parametrize("owner", [True, [1], {"id": 1}, "1e0", 1.5, "abc", 999999, 3, 4],
                         ids=["true", "list", "object", "exp", "float", "text", "no-such-user", "assistant", "manager"])
def test_ten_more_with_a_malformed_or_non_salesperson_owner_is_404_not_a_bypass(bd_seeded, bd_db, bd_as_user, owner):
    batches = bd_db.execute("select count(*) as n from bd.task_batches").fetchone()["n"]
    r = bd_as_user(1).post("/api/bd/week/ten-more", json={"owner": owner})
    assert r.status_code == 404 and r.json()["error"] == "not_found", (owner, r.text)
    assert bd_db.execute("select count(*) as n from bd.task_batches").fetchone()["n"] == batches


def test_a_salesperson_reads_and_edits_a_colleagues_contact(bd_seeded, bd_db, bd_as_user):
    """The contract has no "own" rule on a contact (unlike the week and the task buttons): the whole
    team shares the list, so Blair reads, edits, confirms, logs a note on and archives a contact Avery
    owns, and the contact stays Avery's."""
    cid = SHARED_CONTACT
    assert bd_db.execute("select owner_id from bd.contacts where id = %s", (cid,)).fetchone()["owner_id"] == 1
    for uid in UID.values():
        assert bd_as_user(uid).get("/api/bd/contacts/%d" % cid).status_code == 200
        assert bd_as_user(uid).get("/api/bd/contacts/%d/interactions" % cid).status_code == 200
    blair = bd_as_user(BLAIR)
    r = blair.patch("/api/bd/contacts/%d" % cid, json={"notes": "Blair added this."})
    assert r.status_code == 200 and r.json()["contact"]["notes"] == "Blair added this."
    assert r.json()["contact"]["owner"]["id"] == 1, "an edit of the notes does not move the contact"
    assert blair.post("/api/bd/contacts/%d/confirm" % cid, json={"confirmed": True}).status_code == 200
    log = blair.post("/api/bd/contacts/%d/interactions" % cid, json={"kind": "note", "summary": "Blair's note"})
    assert log.status_code == 200 and log.json()["interaction"]["user"]["id"] == BLAIR
    assert blair.post("/api/bd/contacts/%d/archive" % cid, json={"archived": True}).status_code == 200
    assert bd_db.execute("select archived_at from bd.contacts where id = %s", (cid,)).fetchone()["archived_at"]


def test_a_patch_cannot_restore_or_archive_a_contact_by_an_archived_key(bd_seeded, bd_db, bd_as_user):
    """Archiving and restoring go through POST .../archive only. A PATCH that names archived_at or
    archived is taken for its other fields and leaves the archive as it was, both ways."""
    cid = THROWAWAY_CONTACT
    avery = bd_as_user(1)

    def archived_at():
        return bd_db.execute("select archived_at from bd.contacts where id = %s", (cid,)).fetchone()["archived_at"]

    r = avery.patch("/api/bd/contacts/%d" % cid, json={"archived_at": "2026-11-01T09:00:00-06:00", "archived": True,
                                                       "notes": "live"})
    assert r.status_code == 200, r.text
    assert archived_at() is None, "a PATCH archived a live contact"
    assert avery.post("/api/bd/contacts/%d/archive" % cid, json={"archived": True}).status_code == 200
    was = archived_at()
    assert was is not None
    r = avery.patch("/api/bd/contacts/%d" % cid, json={"archived_at": None, "archived": False, "notes": "n"})
    assert r.status_code == 200, r.text
    row = bd_db.execute("select archived_at, notes from bd.contacts where id = %s", (cid,)).fetchone()
    assert (row["archived_at"], row["notes"]) == (was, "n"), "a PATCH restored an archived contact"
    assert avery.post("/api/bd/contacts/%d/archive" % cid, json={"archived": False}).status_code == 200
    assert archived_at() is None


def test_a_duplicate_flag_can_only_be_cleared_never_set_by_a_patch(bd_seeded, bd_as_user):
    """duplicate_of is the server's to set (the duplicate check); a PATCH may only clear it (null).
    Setting it is 400 and the refused PATCH saves nothing, its other fields included."""
    avery = bd_as_user(1)
    url = "/api/bd/contacts/%d" % THROWAWAY_CONTACT
    before = avery.get(url).json()["contact"]
    r = avery.patch(url, json={"duplicate_of": SHARED_CONTACT, "notes": "must not save"})
    assert r.status_code == 400 and "duplicate_of" in r.json().get("fields", {}), r.text
    assert avery.get(url).json()["contact"] == before, "a refused PATCH saves nothing"


def test_company_create_and_patch_ignore_server_owned_keys(bd_seeded, bd_db, bd_as_user):
    avery = bd_as_user(1)
    r = avery.post("/api/bd/companies", json={"name": "Mass Assign Company", "id": 777777,
                                              "normalized_name": "hacked", "created_at": "2001-01-01"})
    assert r.status_code == 201, r.text
    cid = r.json()["company"]["id"]
    assert cid != 777777
    r = avery.patch("/api/bd/companies/%d" % cid, json={"city": "Lenexa", "id": 1, "normalized_name": "hacked"})
    assert r.status_code == 200 and r.json()["company"]["id"] == cid
    row = bd_db.execute("select normalized_name, city, created_at from bd.companies where id = %s", (cid,)).fetchone()
    assert row["normalized_name"] == "mass assign" and row["city"] == "Lenexa"
    assert row["created_at"].year == 2026


HOSTILE = {"user_id": 3, "user": {"id": 3, "name": "Casey Moret"}, "counts_as_touch": True, "provider": "quo",
           "external_id": "EXT-MASS-1", "recording_url": "https://evil.example/x.mp3", "contact_id": 22,
           "id": 999999, "created_at": "2001-01-01T00:00:00-06:00", "followup_status": "sent",
           "followup_at": "2001-01-01"}


def test_a_logged_entry_is_always_the_callers_and_the_server_counts_it(bd_seeded, bd_db, bd_as_user):
    """A body that names another person, a provider, an external id, a recording or counts_as_touch
    changes none of it: the author is the caller, the source is manual, the server counts the touch."""
    url = "/api/bd/contacts/%d/interactions" % SHARED_CONTACT
    for kind in ("note", "email", "sms"):
        r = bd_as_user(1).post(url, json=dict(HOSTILE, kind=kind, summary="hostile " + kind))
        assert r.status_code == 200, r.text
        i = r.json()["interaction"]
        assert i["user"]["id"] == 1 and i["counts_as_touch"] is False and i["id"] != 999999
        row = bd_db.execute("select * from bd.interactions where id = %s", (i["id"],)).fetchone()
        assert (row["user_id"], row["contact_id"], row["provider"], row["external_id"], row["recording_url"],
                row["followup_status"]) == (1, SHARED_CONTACT, "manual", None, None, None), row
        assert row["created_at"].year == 2026
    r = bd_as_user(1).post(url, json=dict(HOSTILE, kind="call", outcome="no_answer", summary="rang out"))
    assert r.status_code == 200 and r.json()["interaction"]["counts_as_touch"] is False
    r = bd_as_user(1).post(url, json=dict(HOSTILE, kind="call", outcome="answered", summary="live"))
    assert r.status_code == 200 and r.json()["interaction"]["counts_as_touch"] is True


def test_editing_an_entry_cannot_change_its_author_contact_or_source(bd_seeded, bd_db, bd_as_user):
    r = bd_as_user(1).patch("/api/bd/interactions/%d" % AVERYS_ENTRY,
                            json={"summary": "edited", "user_id": 3, "contact_id": 22, "provider": "quo",
                                  "external_id": "EXT-MASS-2", "recording_url": "https://evil.example/y.mp3",
                                  "counts_as_touch": False, "id": 999999})
    assert r.status_code == 200, r.text
    row = bd_db.execute("select * from bd.interactions where id = %s", (AVERYS_ENTRY,)).fetchone()
    assert row["summary"] == "edited"
    assert (row["user_id"], row["contact_id"], row["provider"], row["external_id"], row["recording_url"],
            row["counts_as_touch"]) == (1, SHARED_CONTACT, "manual", None, None, True), row


def test_changing_a_bd_login_cannot_change_its_email_sign_in_id_or_id(bd_seeded, bd_db, bd_as_user):
    """PATCH /api/bd/admin/users/{id} changes role, active and name only."""
    cols = "id, email, auth_sub, created_at, role, active"
    before = bd_db.execute("select " + cols + " from bd.users where id = %s", (BLAIR,)).fetchone()
    r = bd_as_user(UID["admin"]).patch("/api/bd/admin/users/%d" % BLAIR, json={
        "name": "Blair Renamed", "email": "evil@example.com", "auth_sub": "attacker-sub", "id": 1,
        "created_at": "2001-01-01", "last_seen_at": "2001-01-01"})
    assert r.status_code == 200, r.text
    user = r.json()["user"]
    assert (user["name"], user["id"], user["email"]) == ("Blair Renamed", BLAIR, "blair.fenn@example.com")
    assert bd_db.execute("select " + cols + " from bd.users where id = %s", (BLAIR,)).fetchone() == before
    assert bd_db.execute("select id from bd.users where email = 'evil@example.com'").fetchone() is None


MANAGER_SENTENCE = "Managers can change only how often to follow up."
NON_CADENCE_KEYS = {
    "company": {"name": "Hijacked Works"}, "name": "Renamed By Manager", "title": "CEO", "email": "m@example.com",
    "phone": "913-555-0100", "city": "Nowhere", "industry": "Other", "lead_source": "Other/Misc", "stage": "Won",
    "category": "maintenance", "account_type": "Key", "owner_id": 2, "co_owner_id": 2, "importance": 3,
    "next_step": "x", "next_step_date": "2027-01-01", "promised_date": "2027-01-01", "tags": ["x"], "notes": "x",
    "duplicate_of": None, "id": 5, "source": "workbook", "archived_at": None, "created_at": "2001-01-01T00:00:00-06:00",
    "confirmed": True,
}


def test_a_manager_may_patch_nothing_but_the_cadence(bd_seeded, bd_as_user):
    """Key by key: 403 in the manager's sentence and nothing saved (a refused PATCH saves nothing, so
    one contact serves every key); a cadence key alongside another is refused whole."""
    devon = bd_as_user(UID["manager"])
    url = "/api/bd/contacts/%d" % SHARED_CONTACT
    before = devon.get(url).json()["contact"]
    for key, value in sorted(NON_CADENCE_KEYS.items()):
        r = devon.patch(url, json={key: value})
        assert (r.status_code, r.json()) == (403, forbidden(MANAGER_SENTENCE)), key
    r = devon.patch(url, json={"cadence_override": "monthly", "cadence_override_until": "2027-01-31",
                               "notes": "sneaked in"})
    assert (r.status_code, r.json()) == (403, forbidden(MANAGER_SENTENCE))
    assert devon.get(url).json()["contact"] == before, "a refused PATCH saves nothing"
    r = devon.patch(url, json={"cadence_override": "monthly", "cadence_override_until": "2027-01-31"})
    assert r.status_code == 200 and r.json()["contact"]["cadence_override"] == "monthly"
