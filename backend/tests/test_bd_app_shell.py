"""The BD router on the proposal tool's app (#806): the shell every BD route sits in.

BD's test_app_shell, rewritten for /api/bd/ and the tool's sign-in gate:

  * the proposal tool's own 404, 422 and 500 keep their shapes; BD's envelope appears only under
    /api/bd/;
  * every BD route is behind the tool's gate (401 in the tool's shape), except the telephony
    webhook at its one exact public path;
  * the BD switch: off by default, and off means 503 "not turned on" on every /api/bd/ path before
    any database work; on, a ledger behind the code is 503 "database not up to date";
  * a stopped BD database never slows the tool, and BD answers 503 in about 3 seconds;
  * /api/bd/me, /api/bd/settings and /api/bd/users over the fixture seed; no BD login, a turned-off
    one, or a proposal-tool admin with none is 403;
  * every pending route checks the BD role first, then answers 503; no service-token route exists;
  * the envelope itself, on a small app whose router uses BD's route class.
"""
from __future__ import annotations

import pathlib
import re
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

import main
from _bd_conftest import bd_token_headers
from bd import api as bd_api
from bd import auth as bd_auth
from bd import config as bd_config
from bd import db as bd_dbmod
from bd import errors, web
from bd.routers import pending

BACKEND = pathlib.Path(__file__).resolve().parents[1]
TODAY = "2026-11-04"            # the fixture seed's day (bd/ops/fixture_seed.py FIXTURE_TODAY)
NOT_TURNED_ON = {"ok": False, "error": "unavailable", "message": "The BD CRM is not turned on."}


def concrete(path):
    return path.replace("{id}", "1").replace("{rest}", "anything")


def is_envelope(body, code):
    return (isinstance(body, dict) and body.get("ok") is False and body.get("error") == code
            and isinstance(body.get("message"), str) and body["message"].strip()
            and body["message"][-1] in ".?!")


def is_tool_refusal(resp, status):
    """The proposal tool's own refusal: {"ok": false, "error": "<sentence>"}, no `message`."""
    body = resp.json()
    return (resp.status_code == status and set(body) == {"ok", "error"} and body["ok"] is False
            and isinstance(body["error"], str) and body["error"])


def every_bd_route():
    """(method, path) for every BD route but the catch-all."""
    out = []
    for route in bd_api.bd_routes():
        for method in sorted(route.methods - {"HEAD"}):
            out.append((method, route.path))
    return out


@pytest.fixture
def tool_client():
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.fixture
def no_bd_database(monkeypatch):
    """Fails the test if anything reaches for BD's pool; returns the list of attempts."""
    attempts = []

    def refuse():
        attempts.append(1)
        raise AssertionError("a BD database connection was asked for")

    monkeypatch.setattr(bd_dbmod, "get_pool", refuse)
    return attempts


# ── the proposal tool's own error shapes do not change ───────────────────────────────────────
def test_a_tool_404_422_and_500_keep_their_shapes(tool_client, monkeypatch):
    r = tool_client.get("/api/no-such-tool-route")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}

    r = tool_client.post("/api/price", json=[1, 2])
    assert r.status_code == 422
    assert set(r.json()) == {"detail"} and isinstance(r.json()["detail"], list)

    def boom():
        raise RuntimeError("secret internals")

    monkeypatch.setattr(main.pricing, "list_systems", boom)
    r = tool_client.get("/api/pricing/systems")
    assert r.status_code == 500
    assert r.text == "Internal Server Error" and r.headers["content-type"].startswith("text/plain")


@pytest.mark.parametrize("path", ["/api/bdx/thing", "/api/bd", "/api/b/d/thing", "/api/nope/bd/thing"])
def test_paths_outside_api_bd_get_the_tools_404_not_bds(tool_client, monkeypatch, path):
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    r = tool_client.get(path)
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_an_unknown_bd_path_signed_in_is_bds_404_envelope(tool_client, monkeypatch, no_bd_database):
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    for method in ("GET", "POST", "DELETE"):
        r = tool_client.request(method, "/api/bd/no-such-route")
        assert r.status_code == 404 and is_envelope(r.json(), "not_found"), r.text
        assert r.headers["cache-control"] == "no-store"
    assert no_bd_database == []


def test_a_wrong_method_on_a_bd_route_is_bds_400(tool_client, monkeypatch):
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    r = tool_client.post("/api/bd/me")
    assert r.status_code == 400 and r.json() == {
        "ok": False, "error": "bad_request", "message": "POST is not allowed on /api/bd/me."}
    r = tool_client.delete("/api/bd/review/candidates")
    assert r.status_code == 400 and r.json()["message"] == "DELETE is not allowed on /api/bd/review/candidates."


# ── the gate: the tool's sign-in covers every BD route ───────────────────────────────────────
@pytest.mark.parametrize("method,path", every_bd_route())
def test_every_bd_route_refuses_a_caller_without_a_token(tool_client, monkeypatch, real_verify_identity,
                                                         no_bd_database, method, path):
    import supabase_client

    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    monkeypatch.setattr(supabase_client, "verify_identity", real_verify_identity)
    r = tool_client.request(method, concrete(path), json={} if method in ("POST", "PATCH", "PUT") else None)
    if path == pending.WEBHOOK_PATH:
        # Public by design (the provider will sign it); not built yet, so 503 rather than 401.
        assert r.status_code == 503 and r.json() == {
            "ok": False, "error": "unavailable", "message": pending.message_for(pending.PENDING[(method, path)])}
        return
    assert is_tool_refusal(r, 401), (method, path, r.status_code, r.text)
    assert no_bd_database == []


@pytest.mark.parametrize("path", ["/api/bd/nope", "/api/bd/", "/api/bd/me/extra",
                                  "/api/bd/webhooks/telephony", "/api/bd/webhooks/telephony/",
                                  "/api/bd/webhooks/telephony/other", "/api/bd/webhooks/telephony/quo/x",
                                  "/api/bd/webhooks/telephony/quox"])
def test_only_the_exact_webhook_path_is_public(tool_client, monkeypatch, real_verify_identity, path):
    import supabase_client

    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    monkeypatch.setattr(supabase_client, "verify_identity", real_verify_identity)
    for method in ("GET", "POST"):
        r = tool_client.request(method, path)
        assert is_tool_refusal(r, 401), (method, path, r.status_code, r.text)


def test_the_webhook_is_post_only_and_answers_without_a_sign_in(tool_client, monkeypatch, real_verify_identity):
    import supabase_client

    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    monkeypatch.setattr(supabase_client, "verify_identity", real_verify_identity)
    assert main._auth_is_public(pending.WEBHOOK_PATH, "POST")
    r = tool_client.post(pending.WEBHOOK_PATH, json={"type": "call.completed"})
    assert r.status_code == 503 and r.json()["message"] == "This part is not built yet (Phase 4)."
    r = tool_client.get(pending.WEBHOOK_PATH)
    assert r.status_code == 400 and r.json()["message"] == "GET is not allowed on /api/bd/webhooks/telephony/quo."


def test_no_service_token_route_or_check_exists(tool_client, monkeypatch):
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    assert not [p for _m, p in every_bd_route() if "bd-candidates" in p]
    r = tool_client.post("/api/bd/admin/bd-candidates", json={}, headers={"Authorization": "Bearer anything"})
    assert r.status_code == 404 and is_envelope(r.json(), "not_found")
    for path in ("/api/bd/admin/bd-candidates", "/api/admin/bd-candidates"):
        assert not main._auth_is_public(path, "POST"), path
    for source in sorted((BACKEND / "bd").rglob("*.py")):
        text = source.read_text(encoding="utf-8")
        assert not re.search(r"service_token|SERVICE_TOKEN|compare_digest", text), source


# ── the switch: off by default, and off means nothing touches the database ───────────────────
def test_the_switch_is_off_unless_bd_enabled_is_set(monkeypatch):
    monkeypatch.delenv("BD_ENABLED", raising=False)
    bd_config.reload()
    try:
        assert bd_config.BD_ENABLED is False and web.is_enabled() is False
    finally:
        monkeypatch.undo()
        bd_config.reload()


@pytest.mark.parametrize("method,path", every_bd_route() + [("GET", "/api/bd/no-such-route"),
                                                            ("POST", "/api/bd/me")])
def test_switched_off_every_bd_path_is_503_before_any_database_work(tool_client, monkeypatch, no_bd_database,
                                                                    method, path):
    monkeypatch.setattr(bd_config, "BD_ENABLED", False)
    r = tool_client.request(method, concrete(path), json={} if method in ("POST", "PATCH", "PUT") else None,
                            headers=bd_token_headers("avery.quill@example.com"))
    assert r.status_code == 503 and r.json() == NOT_TURNED_ON, (method, path, r.text)
    assert r.headers["cache-control"] == "no-store"
    assert no_bd_database == [], "the switch was checked after a database connection was asked for"


def test_switched_off_the_tool_is_unchanged(tool_client, monkeypatch, no_bd_database):
    monkeypatch.setattr(bd_config, "BD_ENABLED", False)
    assert tool_client.get("/healthz").json() == {"ok": True}
    assert tool_client.post("/api/price", json={"systems": []}).status_code == 200
    assert no_bd_database == []


def test_a_ledger_behind_the_code_is_503_database_not_up_to_date(bd_seeded, bd_as_user, bd_db_url):
    import _bd_db

    me = bd_as_user(1)
    assert me.get("/api/bd/me").status_code == 200
    with _bd_db.connect(bd_db_url) as owner:
        last = owner.execute("select name, applied_at from bd.schema_migrations order by name desc limit 1").fetchone()
        owner.execute("delete from bd.schema_migrations where name = %s", (last[0],))
        owner.commit()
    try:
        for path in ("/api/bd/me", "/api/bd/settings", "/api/bd/users", "/api/bd/analytics"):
            r = me.get(path)
            assert r.status_code == 503, (path, r.text)
            assert r.json() == {"ok": False, "error": "unavailable", "message": bd_auth.NOT_UP_TO_DATE}
    finally:
        with _bd_db.connect(bd_db_url) as owner:
            owner.execute("insert into bd.schema_migrations (name, applied_at) values (%s, %s)", last)
            owner.commit()
    assert me.get("/api/bd/me").status_code == 200


# ── a stopped BD database never slows the tool ───────────────────────────────────────────────
def test_with_the_bd_database_stopped_the_tool_stays_fast_and_bd_answers_503_in_about_3s(tool_client, monkeypatch):
    """Port 1 on this machine refuses every connection: BD's database is down. The tool's health check
    and a tool route answer at once; BD answers 503 within its 3-second checkout, and the health check
    never asks for a BD connection."""
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    asked = []
    real_get_pool = bd_dbmod.get_pool
    monkeypatch.setattr(bd_dbmod, "get_pool", lambda: (asked.append(1), real_get_pool())[1])
    previous = bd_dbmod.configure("postgresql://bd_app:not-a-secret@127.0.0.1:1/bd_test_stopped?connect_timeout=1")
    try:
        started = time.monotonic()
        r = tool_client.get("/api/bd/me", headers=bd_token_headers("avery.quill@example.com"))
        took = time.monotonic() - started
        assert r.status_code == 503 and r.json() == {"ok": False, "error": "unavailable",
                                                     "message": errors.DB_UNAVAILABLE}
        assert 2.0 <= took < 6.0, took
        assert "not-a-secret" not in r.text and "127.0.0.1" not in r.text
        asked.clear()
        for _ in range(3):
            started = time.monotonic()
            assert tool_client.get("/healthz").json() == {"ok": True}
            assert tool_client.post("/api/price", json={"systems": []}).status_code == 200
            assert time.monotonic() - started < 1.5
        assert asked == [], "the health check or a tool route asked for a BD connection"
    finally:
        bd_dbmod.configure(previous)


# ── signed in, on the fixture seed ───────────────────────────────────────────────────────────
CAN = {
    "salesperson": {"send": True, "analytics": False, "admin": False, "admin_area": False, "import": True,
                    "run_batch": False, "week": True, "pick_owner": False,
                    "add_contact": True, "edit_contact": True, "clear_duplicate": False, "cadence": True, "manage_entries": False},
    "assistant": {"send": False, "analytics": False, "admin": False, "admin_area": True, "import": True,
                  "run_batch": False, "week": False, "pick_owner": False,
                  "add_contact": True, "edit_contact": True, "clear_duplicate": True, "cadence": True, "manage_entries": False},
    "manager": {"send": False, "analytics": True, "admin": False, "admin_area": False, "import": False,
                "run_batch": False, "week": True, "pick_owner": True,
                "add_contact": False, "edit_contact": False, "clear_duplicate": False, "cadence": True, "manage_entries": False},
    "admin": {"send": True, "analytics": True, "admin": True, "admin_area": True, "import": True,
              "run_batch": True, "week": True, "pick_owner": True,
              "add_contact": True, "edit_contact": True, "clear_duplicate": True, "cadence": True, "manage_entries": True},
    "super_admin": {"send": True, "analytics": True, "admin": True, "admin_area": True, "import": True,
                    "run_batch": True, "week": True, "pick_owner": True,
                    "add_contact": True, "edit_contact": True, "clear_duplicate": True, "cadence": True, "manage_entries": True},
}
SEED_PEOPLE = [
    (1, "Avery Quill", "avery.quill@example.com", "salesperson"),
    (3, "Casey Moret", "casey.moret@example.com", "assistant"),
    (4, "Devon Hale", "devon.hale@example.com", "manager"),
    (5, "Emery Stoll", "emery.stoll@example.com", "admin"),
    (6, "Frankie Oduya", "frankie.oduya@example.com", "super_admin"),
]


@pytest.mark.parametrize("uid,name,email,role", SEED_PEOPLE, ids=[p[3] for p in SEED_PEOPLE])
def test_me_for_every_bd_role(bd_seeded, bd_as_user, uid, name, email, role):
    r = bd_as_user(uid).get("/api/bd/me")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"ok", "user", "can", "today", "timezone"}
    assert body["ok"] is True and body["can"] == CAN[role]
    assert body["today"] == TODAY and body["timezone"] == "America/Chicago"
    user = body["user"]
    assert {k: user[k] for k in ("id", "name", "email", "role", "active")} == {
        "id": uid, "name": name, "email": email, "role": role, "active": True}
    assert user["last_seen_at"].endswith("-06:00")       # signing in just refreshed it, in Central
    assert r.headers["cache-control"] == "no-store"


def test_settings_are_the_defaults_on_a_fresh_seed(bd_seeded, bd_as_user):
    want = {
        "bd_cadence": "quarterly",
        "default_frequency": {"maintenance": 3},
        "maintenance_touch_days": 120,
        "weekly": {"new_count": 5, "followup_count": 5, "run_day": "friday", "run_hour": 16, "enabled": False},
        "weekly_meeting_goal": 5,
        "non_dsbc_website_min": 1,
        "lead_sources": ["Current Account", "DSBC Sales", "Website Lead", "Other/Misc"],
        "system_lead_sources": ["DSBC Sales", "Website Lead"],
        "industries": ["Manufacturing", "Other", "Food Processing", "GC", "Life Science", "Restaurant",
                       "Education", "Warehouse", "Retail", "Healthcare"],
        "stages": ["Meeting Set", "Met", "Proposal", "Won"],
        "account_types": ["Utility", "Manufacturing", "Pharma", "GC"],
        "interaction_kinds": ["call", "voicemail", "meeting", "email", "sms", "note", "hosted"],
        "touch_kinds": ["call (answered or meeting set)", "meeting", "hosted"],
        "call_outcomes": ["answered", "voicemail", "no_answer", "meeting_set"],
        "ai_enabled": False,
        "timezone": "America/Chicago",
    }
    for uid in (1, 3, 4):
        r = bd_as_user(uid).get("/api/bd/settings")
        assert r.status_code == 200 and r.json() == {"ok": True, "settings": want}


def test_users_lists_the_active_logins_only(bd_seeded, bd_as_user):
    r = bd_as_user(3).get("/api/bd/users")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "total": 6, "items": [
        {"id": 1, "name": "Avery Quill", "role": "salesperson"},
        {"id": 2, "name": "Blair Fenn", "role": "salesperson"},
        {"id": 3, "name": "Casey Moret", "role": "assistant"},
        {"id": 4, "name": "Devon Hale", "role": "manager"},
        {"id": 5, "name": "Emery Stoll", "role": "admin"},
        {"id": 6, "name": "Frankie Oduya", "role": "super_admin"},
    ]}
    page = bd_as_user(3).get("/api/bd/users", params={"limit": 2, "offset": 1}).json()
    assert page["total"] == 6 and [u["id"] for u in page["items"]] == [2, 3]
    bad = bd_as_user(3).get("/api/bd/users", params={"limit": "lots"})
    assert bad.status_code == 400 and bad.json() == {
        "ok": False, "error": "bad_request", "message": "Some fields need fixing.",
        "fields": {"limit": "Use a whole number."}}


def test_a_turned_off_login_is_refused_everywhere(bd_seeded, bd_as_user):
    gale = bd_as_user(7)                                   # the seed's turned-off salesperson
    for path in ("/api/bd/me", "/api/bd/settings", "/api/bd/users", "/api/bd/interactions/1/recommend"):
        r = gale.request("POST" if path.endswith("recommend") else "GET", path, json={})
        assert r.status_code == 403 and r.json() == {"ok": False, "error": "forbidden",
                                                     "message": bd_auth.TURNED_OFF}, path


def test_a_signed_in_staffer_with_no_bd_login_is_403_on_every_bd_route(bd_seeded, bd_client):
    headers = bd_token_headers("new.hire@example.com")
    for method, path in every_bd_route():
        if path == pending.WEBHOOK_PATH:
            continue
        r = bd_client.request(method, concrete(path), json={} if method == "POST" else None, headers=headers)
        assert r.status_code == 403, (method, path, r.text)
        assert r.json() == {"ok": False, "error": "forbidden", "message": bd_auth.NO_BD_ROLE}


@pytest.mark.parametrize("tool_role", ["admin", "super_admin"])
def test_a_proposal_tool_admin_gets_no_bd_role(bd_seeded, bd_app, bd_client, bd_db, tool_role):
    email = "tool.admin@example.com"
    bd_app.tool_roles[email] = tool_role
    r = bd_client.get("/api/bd/me", headers=bd_token_headers(email))
    assert r.status_code == 403 and r.json()["message"] == bd_auth.NO_BD_ROLE
    assert bd_db.execute("select count(*) as n from bd.users where email = %s", (email,)).fetchone()["n"] == 0


def test_the_tool_role_never_changes_the_bd_role(bd_seeded, bd_app, bd_as_user):
    """A BD salesperson who is a proposal-tool admin is still a salesperson in BD."""
    bd_app.tool_roles["avery.quill@example.com"] = "admin"
    body = bd_as_user(1).get("/api/bd/me").json()
    assert body["user"]["role"] == "salesperson" and body["can"] == CAN["salesperson"]


# ── pending routes: the role check first, then 503 ───────────────────────────────────────────
def _served_by_pending(method, path):
    """True while bd/routers/pending.py is the route that answers (a real router listed earlier wins
    as soon as it exists, and its own tests take over)."""
    for route in bd_api.bd_routes():
        if route.path == path and method in route.methods:
            return route in pending.router.routes
    return False


def router_imports(text):
    """The lines of a router's source that import another router."""
    sibling = re.compile(r"^\s*(from \.(?!\.)|from bd\.routers\b|import bd\.routers\b|from \.\. import routers\b).*$", re.M)
    return [m.group(0).strip() for m in sibling.finditer(text)]


def test_no_bd_router_imports_another_router():
    """What two routers share lives in a bd/ module (weekly.py, paging.py, ...), never in a router, so a
    router does not depend on another router's import order (#807: admin.py once took week.py's owner
    rules)."""
    routers = pathlib.Path(pending.__file__).parent
    bad = {p.name: router_imports(p.read_text(encoding="utf-8")) for p in sorted(routers.glob("*.py"))
           if p.name != "__init__.py"}
    assert {k: v for k, v in bad.items() if v} == {}


def test_the_router_import_check_sees_one():
    assert router_imports("from .. import db, weekly\nfrom .week import list_owner\n") == \
        ["from .week import list_owner"]
    assert router_imports("from ..auth import require_role\nfrom bd.routers.week import x\n") == \
        ["from bd.routers.week import x"]


def test_pending_lists_bd_paths_only():
    for (method, path), phase in pending.PENDING.items():
        assert path.startswith("/api/bd/"), path
        assert phase == "later" or (isinstance(phase, int) and 3 <= phase <= 8), (method, path, phase)
    assert [p for (_m, p), who in pending.ACCESS.items() if who == pending.PUBLIC] == [pending.WEBHOOK_PATH]


ROLE_OF = {1: "salesperson", 3: "assistant", 4: "manager"}


@pytest.mark.parametrize("method,path", sorted(k for k, who in pending.ACCESS.items() if who != pending.PUBLIC))
def test_each_pending_route_checks_the_bd_role_then_answers_503(bd_seeded, bd_as_user, method, path):
    if not _served_by_pending(method, path):
        pytest.skip("built: a real router serves it now (delete it from bd/routers/pending.py)")
    who = pending.ACCESS[(method, path)]
    phase = pending.PENDING[(method, path)]
    # The sentence by hand, from the contract's words, not from message_for.
    sentence = ("This part is not built yet (a later phase)." if phase == "later"
                else "This part is not built yet (Phase %d)." % phase)
    want = {"ok": False, "error": "unavailable", "message": sentence}
    url = concrete(path)
    for uid, role in ROLE_OF.items():
        r = bd_as_user(uid).request(method, url, json={})
        if role in who:
            assert r.status_code == 503 and r.json() == want, (role, r.text)
        else:
            assert r.status_code == 403 and r.json() == {"ok": False, "error": "forbidden",
                                                         "message": "Your role can't do that."}, (role, r.text)
    for admin in (5, 6):                                    # admins always pass
        assert bd_as_user(admin).request(method, url, json={}).json() == want


# ── the envelope, on a small app whose router uses BD's route class ──────────────────────────
class Body(BaseModel):
    name: str
    frequency_per_year: int
    confirmed: bool = False


@pytest.fixture(scope="module")
def mini():
    app = FastAPI()
    router = web.make_router()

    @router.post("/thing")
    def thing(body: Body, limit: int = 10):
        return {"ok": True}

    @router.get("/boom")
    def boom():
        raise RuntimeError("secret internals")

    @router.get("/gone")
    def gone():
        raise errors.not_found("That contact does not exist.")

    @router.get("/fields")
    def fields():
        raise errors.bad_request("New people and follow-ups must add up to 10.",
                                 {"weekly": "New people and follow-ups must add up to 10."})

    @router.get("/busy")
    def busy():
        raise bd_dbmod.Busy("every slot is taken")

    @app.post("/plain")
    def plain(body: Body):
        return {"ok": True}

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


def test_422_is_rewrapped_as_400_with_plain_fields(mini):
    r = mini.post("/thing?limit=abc", json={"frequency_per_year": "often", "confirmed": "maybe"})
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False and body["error"] == "bad_request" and body["message"] == "Some fields need fixing."
    assert body["fields"] == {"name": "Required.", "frequency_per_year": "Use a whole number.",
                              "confirmed": "Use true or false.", "limit": "Use a whole number."}


def test_a_route_outside_the_bd_router_keeps_fastapis_422(mini):
    r = mini.post("/plain", json={"frequency_per_year": "often"})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)


def test_malformed_json_is_400(mini):
    r = mini.post("/thing", content=b'{"name": ', headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    assert r.json() == {"ok": False, "error": "bad_request", "message": "The request body is not valid JSON.",
                        "fields": {"body": "The request body is not valid JSON."}}


def test_api_errors_keep_their_words_and_fields(mini):
    r = mini.get("/gone")
    assert r.status_code == 404 and r.json() == {"ok": False, "error": "not_found",
                                                 "message": "That contact does not exist."}
    r = mini.get("/fields")
    assert r.status_code == 400
    assert r.json() == {"ok": False, "error": "bad_request", "message": "New people and follow-ups must add up to 10.",
                        "fields": {"weekly": "New people and follow-ups must add up to 10."}}


def test_an_unhandled_error_is_a_500_envelope_that_leaks_nothing(mini):
    r = mini.get("/boom")
    assert r.status_code == 500
    assert r.json() == {"ok": False, "error": "error", "message": "The server had a problem. Try again in a minute."}
    assert "secret" not in r.text and r.headers["cache-control"] == "no-store"


def test_a_busy_bd_is_503(mini):
    r = mini.get("/busy")
    assert r.status_code == 503 and r.json() == {"ok": False, "error": "unavailable", "message": errors.DB_BUSY}


@pytest.mark.parametrize("status,code", [(400, "bad_request"), (401, "unauthenticated"), (403, "forbidden"),
                                         (404, "not_found"), (409, "conflict"), (429, "rate_limited"),
                                         (503, "unavailable"), (500, "error")])
def test_status_codes_map_to_the_contracts_words(status, code):
    assert errors.code_for(status) == code
    e = errors.ApiError(status)
    assert e.code == code and e.message.endswith(".")
