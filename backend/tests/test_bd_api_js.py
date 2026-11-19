"""BD's API helper on the tool (#806, spec #802 Q6): frontend/bd/js/bd-api.js, window.BDApi.

  * it calls /api/bd/ only: a path anywhere else is refused with no request at all;
  * it sends the tool's bearer token (TWAuth.token()) and waits for TWAuth.tokenReady first;
  * a BD envelope {ok: false, error: <code>, message} becomes an Error with that message, code, status
    and fields; the tool's own 401 and 403 shape {ok: false, error: <sentence>} (no message) shows
    that sentence; a page that is not JSON, and no network at all, get a plain sentence;
  * BD's mock mode is gone: no mock data, no ?mock or ?as switch, no preview gate.

Executed in node by tests/js/bd/bd-page-harness.js, with the tool's shell stood in for by TWAuth.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from _node import last_json_line, require_node, run_node

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "bd" / "bd-page-harness.js"
API_JS = FRONTEND / "bd" / "js" / "bd-api.js"

ME = {"ok": True, "user": {"id": 1, "name": "Avery Quill", "role": "salesperson"}, "can": {"week": True},
      "today": "2026-11-04", "timezone": "America/Chicago"}


def run(tmp_path, calls, responses=None, token="tok-123", ready=True, fetch_fails=False, name="s"):
    require_node()
    sc = {"scripts": ["bd/js/bd-api.js"], "token": token, "ready": ready, "calls": calls,
          "responses": responses or {}, "fetchFails": fetch_fails}
    f = tmp_path / ("%s.json" % name)
    f.write_text(json.dumps(sc), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = last_json_line(proc.stdout)
    assert out["threw"] is None, out["threw"]
    return out


def test_a_bd_path_is_fetched_with_the_tools_token(tmp_path):
    out = run(tmp_path, [{"fn": "get", "path": "/api/bd/me"}],
              {"GET /api/bd/me": {"status": 200, "body": ME}})
    assert out["calls"] == [{"ok": ME}]
    assert [(f["method"], f["url"]) for f in out["fetches"]] == [("GET", "/api/bd/me")]
    assert out["fetches"][0]["headers"]["Authorization"] == "Bearer tok-123"


def test_a_body_is_sent_as_json(tmp_path):
    out = run(tmp_path, [{"fn": "post", "path": "/api/bd/contacts", "body": {"name": "Rowan Pike"}}],
              {"POST /api/bd/contacts": {"status": 200, "body": {"ok": True, "id": 7}}})
    f = out["fetches"][0]
    assert f["method"] == "POST" and f["headers"]["Content-Type"] == "application/json"
    assert json.loads(f["body"]) == {"name": "Rowan Pike"}


@pytest.mark.parametrize("path", ["/api/me", "/api/bd", "/api/bdx/me", "/bd/index.html", "api/bd/me",
                                  "https://example.com/api/bd/me", "//example.com/api/bd/me",
                                  "/api/bd/../me", "/api/bd/./me", "/api/bd/me\\x", "/api/drafts"])
def test_a_path_outside_api_bd_is_refused_without_a_request(tmp_path, path):
    out = run(tmp_path, [{"fn": "get", "path": path}])
    assert out["fetches"] == [], "BDApi sent %r" % path
    err = out["calls"][0]["error"]
    assert err["status"] == 0 and "not a BD CRM address" in err["message"]


def test_nothing_is_sent_before_the_token_is_ready(tmp_path):
    require_node()
    sc = {"scripts": ["bd/js/bd-api.js"], "token": None, "ready": False, "calls": []}
    f = tmp_path / "wait.json"
    f.write_text(json.dumps(sc), encoding="utf-8")
    # A call made while tokenReady never settles: the harness reports no fetch at all.
    js = tmp_path / "wait.js"
    js.write_text(HARNESS.read_text(encoding="utf-8").replace(
        "const calls = [];", "const calls = []; ctx.BDApi.get('/api/bd/me');"), encoding="utf-8")
    proc = run_node(js, FRONTEND, f)
    assert proc.returncode == 0, proc.stderr[-3000:]
    assert last_json_line(proc.stdout)["fetches"] == []


def test_a_bd_envelope_becomes_its_message_code_and_fields(tmp_path):
    body = {"ok": False, "error": "bad_request", "message": "Some fields need fixing.",
            "fields": {"name": "Add a name."}}
    out = run(tmp_path, [{"fn": "post", "path": "/api/bd/contacts", "body": {}}],
              {"POST /api/bd/contacts": {"status": 400, "body": body}})
    assert out["calls"][0]["error"] == {"message": "Some fields need fixing.", "status": 400,
                                        "code": "bad_request", "fields": {"name": "Add a name."}}


def test_no_bd_role_shows_bds_sentence(tmp_path):
    body = {"ok": False, "error": "forbidden", "message": "You don't have a BD role. Ask a BD admin to add you."}
    out = run(tmp_path, [{"fn": "get", "path": "/api/bd/me"}], {"GET /api/bd/me": {"status": 403, "body": body}})
    err = out["calls"][0]["error"]
    assert (err["status"], err["code"]) == (403, "forbidden")
    assert err["message"] == "You don't have a BD role. Ask a BD admin to add you."


@pytest.mark.parametrize("status,sentence,code", [
    (401, "Sign-in expired. Sign in again.", "unauthenticated"),
    (403, "Your account is paused. Ask an admin to turn it back on.", "forbidden"),
])
def test_the_tools_gate_shape_shows_its_own_sentence(tmp_path, status, sentence, code):
    """The tool's sign-in gate answers {ok: false, error: <sentence>} with no message field."""
    out = run(tmp_path, [{"fn": "get", "path": "/api/bd/me"}],
              {"GET /api/bd/me": {"status": status, "body": {"ok": False, "error": sentence}}})
    err = out["calls"][0]["error"]
    assert (err["status"], err["code"], err["message"]) == (status, code, sentence)


def test_a_page_that_is_not_json_and_no_network_read_plainly(tmp_path):
    out = run(tmp_path, [{"fn": "get", "path": "/api/bd/me"}],
              {"GET /api/bd/me": {"status": 502, "text": "<html>Bad gateway</html>"}})
    assert out["calls"][0]["error"]["message"] == "The server had a problem. Try again in a minute."
    out = run(tmp_path, [{"fn": "get", "path": "/api/bd/me"}], fetch_fails=True, name="net")
    err = out["calls"][0]["error"]
    assert (err["status"], err["code"]) == (0, "network")
    assert err["message"] == "Can't reach the server. Check your connection and try again."


def test_the_mock_mode_is_gone():
    src = API_JS.read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/|//[^\n]*", "", src, flags=re.S)
    for word in ("MOCK", "BDMock", "mock-data", "readFlag", "openGate", "decideMode", "localStorage",
                 "sessionStorage", "location.search", "BDAuth", "BD_API_BASE"):
        assert word not in code, "bd-api.js still has %r" % word
    assert '"/api/bd/"' in code, "bd-api.js names its base, /api/bd/"
