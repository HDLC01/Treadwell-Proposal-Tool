"""The BD home, /bd/ (#806): it greets the person by name and says their BD role, from /api/bd/me.

  * a BD login: "Good morning, Avery" (the hour in Central) and "Your BD role: Salesperson";
  * no BD login, a turned-off one, or a proposal-tool admin with no BD role: the page shows the
    server's own sentence ("You don't have a BD role. ..."), and no data;
  * the tool's sign-in gate's 401/403 shape (no message field) and BD's 503s show their sentence too;
  * it asks /api/bd/me through the tool's shell (TWAuth.bdMe), the one answer the sidebar's BD group
    also reads, so the page costs no second request; and it waits for TWAuth.ready, so a page the
    tool has refused (its refusal card) is never painted over;
  * every value goes in as text, never as markup.

This Week fills the page in the next ticket. Executed in node by tests/js/bd/bd-page-harness.js, with
the BD shell's scripts in the page's own order.
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from _node import last_json_line, require_node, run_node

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "bd" / "bd-page-harness.js"
PAGE = FRONTEND / "bd" / "index.html"
IDS = ["bd-greeting", "bd-role", "bd-home-note", "bd-home-note-text"]
MORNING = "2026-11-04T09:30:00-06:00"


def page_scripts():
    """The page's own local scripts after the tool's shell, in its order (bd/js/...)."""
    srcs = re.findall(r'<script src="(/[^"]+)"', PAGE.read_text(encoding="utf-8"))
    return [s.lstrip("/") for s in srcs if s.startswith("/bd/")]


def me(name, role):
    return {"status": 200, "body": {"ok": True, "user": {"id": 4, "name": name, "email": "avery.quill@example.com",
                                                         "role": role, "active": True},
                                    "can": {}, "today": "2026-11-04", "timezone": "America/Chicago"}}


def run(tmp_path, bd_me, now=MORNING, ready=True, name="s"):
    require_node()
    sc = {"scripts": page_scripts(), "token": "tok", "ready": ready, "bdMe": bd_me, "now": now, "ids": IDS}
    f = tmp_path / ("%s.json" % name)
    f.write_text(json.dumps(sc), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = last_json_line(proc.stdout)
    assert out["threw"] is None, out["threw"]
    return out


def test_the_page_runs_the_bd_shell_then_its_own_script():
    assert page_scripts() == ["bd/js/bd-icons.js", "bd/js/bd-api.js", "bd/js/bd-shared.js",
                              "bd/js/bd-core.js", "bd/js/bd-home.js"]


@pytest.mark.parametrize("now,hello", [
    ("2026-11-04T09:30:00-06:00", "Good morning, Avery"),
    ("2026-11-04T13:05:00-06:00", "Good afternoon, Avery"),
    ("2026-11-04T18:45:00-06:00", "Good evening, Avery"),
    # 23:30 UTC on Nov 4 is 5:30 PM in Kansas City: the Central hour, not the machine's.
    ("2026-11-04T23:30:00+00:00", "Good evening, Avery"),
])
def test_a_bd_login_is_greeted_by_first_name(tmp_path, now, hello):
    out = run(tmp_path, me("Avery Quill", "salesperson"), now=now)
    assert out["els"]["bd-greeting"]["text"] == hello
    assert out["els"]["bd-role"]["text"] == "Your BD role: Salesperson"


@pytest.mark.parametrize("role,label", [("salesperson", "Salesperson"), ("assistant", "Assistant"),
                                        ("manager", "Manager"), ("admin", "Admin"),
                                        ("super_admin", "Super admin")])
def test_each_bd_role_is_named_in_words(tmp_path, role, label):
    out = run(tmp_path, me("Avery Quill", role), name=role)
    assert out["els"]["bd-role"]["text"] == "Your BD role: " + label


def test_the_week_is_said_to_come_next(tmp_path):
    out = run(tmp_path, me("Avery Quill", "salesperson"))
    note = out["els"]["bd-home-note"]
    assert note["hidden"] is False and "This Week" in out["els"]["bd-home-note-text"]["text"]


@pytest.mark.parametrize("answer,sentence", [
    ({"status": 403, "body": {"ok": False, "error": "forbidden",
                              "message": "You don't have a BD role. Ask a BD admin to add you."}},
     "You don't have a BD role. Ask a BD admin to add you."),
    ({"status": 403, "body": {"ok": False, "error": "forbidden",
                              "message": "Your BD login is turned off. Ask a BD admin to turn it back on."}},
     "Your BD login is turned off. Ask a BD admin to turn it back on."),
    # the tool's own sign-in gate: {ok: false, error: <sentence>}, no message field
    ({"status": 403, "body": {"ok": False, "error": "Your account is paused. Ask an admin to turn it back on."}},
     "Your account is paused. Ask an admin to turn it back on."),
    ({"status": 401, "body": {"ok": False, "error": "Sign-in expired. Sign in again."}},
     "Sign-in expired. Sign in again."),
    ({"status": 503, "body": {"ok": False, "error": "unavailable", "message": "The BD CRM is not turned on."}},
     "The BD CRM is not turned on."),
    ({"status": 0, "body": None}, "Can't reach the server. Check your connection and try again."),
    ({"status": 502, "body": None}, "The BD CRM isn't answering right now. Try again in a minute."),
])
def test_no_bd_access_shows_the_servers_sentence_and_no_data(tmp_path, answer, sentence):
    out = run(tmp_path, answer)
    assert out["els"]["bd-greeting"]["text"] == "BD CRM"
    assert out["els"]["bd-role"]["text"] == sentence
    assert out["els"]["bd-home-note"]["hidden"] is True


def test_a_bd_code_alone_is_not_shown_as_a_sentence(tmp_path):
    out = run(tmp_path, {"status": 403, "body": {"ok": False, "error": "forbidden"}})
    assert out["els"]["bd-role"]["text"] == "You don't have a BD role."


def test_values_go_in_as_text(tmp_path):
    out = run(tmp_path, me("<img src=x onerror=alert(1)> Quill", "salesperson"))
    greeting = out["els"]["bd-greeting"]
    assert greeting["text"] == "Good morning, <img"
    assert "<img" not in greeting["html"]
    hostile = {"status": 403, "body": {"ok": False, "error": "forbidden", "message": "<b>No</b> role"}}
    out = run(tmp_path, hostile, name="hostile")
    assert out["els"]["bd-role"]["text"] == "<b>No</b> role" and "<b>" not in out["els"]["bd-role"]["html"]


def test_one_request_for_me_shared_with_the_sidebar(tmp_path):
    out = run(tmp_path, me("Avery Quill", "salesperson"))
    assert out["fetches"] == [], "the page asks TWAuth.bdMe(), never /api/bd/me on its own"


def test_a_page_the_tool_refused_is_not_painted_over(tmp_path):
    out = run(tmp_path, me("Avery Quill", "salesperson"), ready=False)
    assert out["els"]["bd-greeting"]["text"] == "" and out["els"]["bd-role"]["text"] == ""
