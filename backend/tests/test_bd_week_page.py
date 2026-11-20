"""This Week, /bd/ (#807): how the page starts, in node, with the tool's shell stood in for.

BD's This Week moved in over #806's greeting home page. Before it draws a week it decides, from the
one /api/bd/me answer the sidebar's BD group also reads (TWAuth.bdMe), whether to draw one at all:

  * no BD login, a turned-off one, the tool's sign-in gate's 401/403 (no message field), BD's 503s and
    no network: the page says the server's own sentence (TWAuth.bdFailure's words, the same the
    sidebar shows) and shows no data: no summary card, no week request;
  * ROLE HOME (BD's old shell's redirect, now in the page): a role whose BD home is Contacts, the
    assistant (can.week false), is sent to the Contacts page with location.replace, before any week
    request. The week route refusing a role (403) sends it there too;
  * a manager or admin with no ?owner= is asked whose week to look at (GET /api/bd/users), and no week
    is asked for until they choose;
  * a salesperson's week is asked for at /api/bd/week (BD's routes live under /api/bd/ now); a week
    that does not load says the server's sentence and offers Try again;
  * a page the tool refused (TWAuth.ready never settles) is never painted over;
  * every value goes in as text.

Executed by tests/js/bd/bd-page-harness.js with the tool's crm-core.js and the page's scripts in the
page's own order. The week itself, drawn and used, is tests/test_bd_e2e_week.py (a real Chromium).
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
IDS = ["main", "wk-eyebrow", "wk-greeting", "week-sub", "live", "summary", "wk-layout", "wk-main", "lists",
       "finish", "wk-tray", "owner-field", "owner-pick"]
MORNING = "2026-11-04T09:30:00-06:00"
CONTACTS = "/bd/contacts.html"

# BD's can() by hand (api-contract.md): "week" for every BD role but the assistant; "send" for a
# salesperson and the admins; "run_batch" for the admins; "pick_owner" for a manager and the admins.
CAN = {
    "salesperson": {"week": True, "send": True, "run_batch": False, "pick_owner": False},
    "assistant": {"week": False, "send": False, "run_batch": False, "pick_owner": False},
    "manager": {"week": True, "send": False, "run_batch": False, "pick_owner": True},
    "admin": {"week": True, "send": True, "run_batch": True, "pick_owner": True},
}


def page_scripts():
    """The page's own local scripts after the tool's shell, in its order (bd/js/...)."""
    srcs = re.findall(r'<script src="(/[^"]+)"', PAGE.read_text(encoding="utf-8"))
    return [s.lstrip("/") for s in srcs if s.startswith("/bd/")]


def me(name, role, uid=1):
    return {"status": 200, "body": {"ok": True, "user": {"id": uid, "name": name, "email": "avery.quill@example.com",
                                                         "role": role, "active": True},
                                    "can": CAN[role], "today": "2026-11-04", "timezone": "America/Chicago"}}


def run(tmp_path, bd_me, responses=None, ready=True, name="s"):
    require_node()
    sc = {"scripts": ["js/crm-core.js"] + page_scripts(), "token": "tok", "ready": ready, "bdMe": bd_me,
          "now": MORNING, "ids": IDS, "responses": responses or {}}
    f = tmp_path / ("%s.json" % name)
    f.write_text(json.dumps(sc), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = last_json_line(proc.stdout)
    assert out["threw"] is None, out["threw"]
    return out


def asked(out):
    return [(f["method"], f["url"].split("?")[0]) for f in out["fetches"]]


def test_the_page_runs_the_bd_shell_then_the_call_sheet_then_the_week():
    assert page_scripts() == ["bd/js/bd-api.js", "bd/js/bd-shared.js", "bd/js/bd-core.js", "bd/js/bd-call.js",
                              "bd/js/bd-week.js"]


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
    assert out["els"]["wk-greeting"]["text"] == "BD CRM"
    assert out["els"]["week-sub"]["text"] == sentence
    assert out["els"]["summary"]["hidden"] is True
    assert out["els"]["wk-tray"]["hidden"] is True
    assert out["els"]["lists"]["text"] == ""
    assert out["fetches"] == [], "no week, no settings: there is nothing this person may read"
    assert out["replaced"] == []


def test_a_bd_code_alone_is_not_shown_as_a_sentence(tmp_path):
    out = run(tmp_path, {"status": 403, "body": {"ok": False, "error": "forbidden"}})
    assert out["els"]["week-sub"]["text"] == "You don't have a BD role."


def test_the_assistant_is_sent_to_the_contacts_page_before_any_week_request(tmp_path):
    """Her BD home is Contacts (BD's old shell sent her there; the page does it now)."""
    out = run(tmp_path, me("Casey Moret", "assistant", uid=3))
    assert out["replaced"] == [CONTACTS]
    assert out["fetches"] == []


def test_a_role_the_week_route_refuses_is_sent_to_the_contacts_page(tmp_path):
    refused = {"status": 403, "body": {"ok": False, "error": "forbidden", "message": "The weekly list is the salesperson's."}}
    out = run(tmp_path, me("Avery Quill", "salesperson"), responses={"GET /api/bd/week": refused,
                                                                     "GET /api/bd/settings": {"status": 200, "body": {"ok": True, "settings": {}}}})
    assert ("GET", "/api/bd/week") in asked(out)
    assert out["replaced"] == [CONTACTS]


def test_a_salesperson_asks_for_the_week_and_the_settings_under_api_bd(tmp_path):
    down = {"status": 503, "body": {"ok": False, "error": "unavailable", "message": "The BD database is not answering."}}
    out = run(tmp_path, me("Avery Quill", "salesperson"), responses={"GET /api/bd/week": down})
    assert sorted(set(asked(out))) == [("GET", "/api/bd/settings"), ("GET", "/api/bd/week")]
    assert all(f["headers"].get("Authorization") == "Bearer tok" for f in out["fetches"])
    assert "The BD database is not answering." in out["els"]["lists"]["text"]
    assert 'id="retry"' in out["els"]["lists"]["html"] and "Try again" in out["els"]["lists"]["text"]
    assert out["replaced"] == []


@pytest.mark.parametrize("role", ["manager", "admin"])
def test_a_manager_or_admin_is_asked_whose_week_and_no_week_is_asked_for(tmp_path, role):
    users = {"status": 200, "body": {"ok": True, "total": 4, "items": [
        {"id": 1, "name": "Avery Quill", "role": "salesperson"},
        {"id": 2, "name": "Blair Fenn", "role": "salesperson"},
        {"id": 3, "name": "Casey Moret", "role": "assistant"},
        {"id": 4, "name": "Devon Hale", "role": "manager"}]}}
    out = run(tmp_path, me("Devon Hale", role, uid=4), responses={"GET /api/bd/users": users}, name=role)
    assert ("GET", "/api/bd/week") not in asked(out)
    assert out["els"]["week-sub"]["text"] == "Choose whose week to look at."
    assert out["els"]["wk-greeting"]["text"] == "Good morning, Devon"
    lists = out["els"]["lists"]
    assert "Whose week?" in lists["text"]
    # The salespeople, and only they: an assistant or a manager has no weekly list.
    assert re.findall(r'data-pick="(\d+)"', lists["html"]) == ["1", "2"]
    assert "Casey" not in lists["text"] and "Devon" not in lists["text"]


def test_one_request_for_me_shared_with_the_sidebar(tmp_path):
    out = run(tmp_path, me("Casey Moret", "assistant", uid=3))
    assert ("GET", "/api/bd/me") not in asked(out), "the page asks TWAuth.bdMe(), never /api/bd/me on its own"


def test_a_page_the_tool_refused_is_not_painted_over(tmp_path):
    out = run(tmp_path, me("Avery Quill", "salesperson"), ready=False)
    assert out["els"]["wk-greeting"]["text"] == "" and out["els"]["week-sub"]["text"] == ""
    assert out["fetches"] == [] and out["replaced"] == []


def test_values_go_in_as_text(tmp_path):
    hostile = {"status": 403, "body": {"ok": False, "error": "forbidden", "message": "<b>No</b> role"}}
    out = run(tmp_path, hostile)
    sub = out["els"]["week-sub"]
    assert sub["text"] == "<b>No</b> role" and "<b>" not in sub["html"]
    users = {"status": 200, "body": {"ok": True, "total": 1, "items": [
        {"id": 1, "name": "<img src=x onerror=alert(1)>", "role": "salesperson"}]}}
    out = run(tmp_path, me("Devon Hale", "manager", uid=4), responses={"GET /api/bd/users": users}, name="hostile")
    assert "<img" not in out["els"]["lists"]["html"] and "&lt;img" in out["els"]["lists"]["html"]


# ── the empty week (no list yet): its words and buttons come from the server ─────────────────────
def empty_week():
    """A WeekView with no batch (docs/bd/api-contract.md), as GET /api/bd/week answers before Friday."""
    return {"status": 200, "body": {"ok": True, "week": {
        "week_start": "2026-11-02", "week_end": "2026-11-08", "owner": {"id": 1, "name": "Avery Quill"},
        "batch": None, "batches": [], "tasks": [], "done_count": 0, "total": 0, "due_count": 0,
        "pace": {"year": 2026, "as_of": "2026-11-04", "required_to_date": 0.0, "completed": 0, "target_total": 0,
                 "pct": 0, "delta": 0, "label": "2026 BD Pace: 0%"},
        "weekly_meetings": {"count": 0, "goal": 5, "non_dsbc_website": 0, "min": 1}, "touches_this_week": 0}}}


def settings(run_day="friday", run_hour=16):
    return {"status": 200, "body": {"ok": True, "settings": {"ai_enabled": False, "weekly": {
        "new_count": 5, "followup_count": 5, "run_day": run_day, "run_hour": run_hour, "enabled": True}}}}


def empty_text(out):
    return re.sub(r"\s+", " ", out["els"]["lists"]["text"])


@pytest.mark.parametrize("run_day, run_hour, words", [
    ("thursday", 9, "The next list arrives Thursday at 9 AM."),
    ("friday", 16, "The next list arrives Friday at 4 PM."),
    ("monday", 0, "The next list arrives Monday at 12 AM."),
    ("saturday", 12, "The next list arrives Saturday at 12 PM."),
    ("sunday", 23, "The next list arrives Sunday at 11 PM."),
])
def test_the_empty_week_says_when_the_next_list_arrives_from_the_settings(tmp_path, run_day, run_hour, words):
    """settings.weekly.run_day / run_hour are what the Friday worker runs on (bd/weekly_worker.py)."""
    out = run(tmp_path, me("Avery Quill", "salesperson"),
              responses={"GET /api/bd/week": empty_week(), "GET /api/bd/settings": settings(run_day, run_hour)})
    assert "Nothing on the list this week." in empty_text(out)
    assert words in empty_text(out), empty_text(out)


def test_without_the_settings_the_empty_week_says_friday_at_4_pm(tmp_path):
    down = {"status": 503, "body": {"ok": False, "error": "unavailable", "message": "Not now."}}
    out = run(tmp_path, me("Avery Quill", "salesperson"),
              responses={"GET /api/bd/week": empty_week(), "GET /api/bd/settings": down})
    assert "The next list arrives Friday at 4 PM." in empty_text(out), empty_text(out)


def test_what_the_page_offers_follows_can_and_not_the_role_name(tmp_path):
    """The page reads /api/bd/me's can (bd/auth.py can()), never a role name: a login whose can grants
    only "week" gets no picker and no buttons, whatever its role says, and one whose can grants
    "send" and "run_batch" gets Give me 10 more and the manual run."""
    bare = me("Emery Stoll", "admin", uid=5)
    bare["body"]["can"] = {"week": True, "send": False, "run_batch": False, "pick_owner": False}
    out = run(tmp_path, bare, responses={"GET /api/bd/week": empty_week(), "GET /api/bd/settings": settings()},
              name="bare")
    assert ("GET", "/api/bd/week") in asked(out), "no pick_owner: no chooser, the week is asked for"
    html = out["els"]["lists"]["html"]
    assert "Nothing on the list this week." in out["els"]["lists"]["text"]
    assert 'data-act="ten-more"' not in html and 'data-act="run-weekly"' not in html

    full = me("Avery Quill", "salesperson")
    full["body"]["can"] = {"week": True, "send": True, "run_batch": True, "pick_owner": False}
    out = run(tmp_path, full, responses={"GET /api/bd/week": empty_week(), "GET /api/bd/settings": settings()},
              name="full")
    html = out["els"]["lists"]["html"]
    assert 'data-act="ten-more"' in html and 'data-act="run-weekly"' in html

    picker = me("Avery Quill", "salesperson")
    picker["body"]["can"] = {"week": True, "send": False, "run_batch": False, "pick_owner": True}
    users = {"status": 200, "body": {"ok": True, "total": 1, "items": [{"id": 1, "name": "Avery Quill", "role": "salesperson"}]}}
    out = run(tmp_path, picker, responses={"GET /api/bd/users": users}, name="picker")
    assert ("GET", "/api/bd/week") not in asked(out)
    assert out["els"]["week-sub"]["text"] == "Choose whose week to look at."


# ── a task's name opens the contact page (#808) ──────────────────────────────────────────────────
def week_with_dana():
    """Avery's week with one open follow-up, Dana Whitlow (contact 21), as GET /api/bd/week answers."""
    out = empty_week()
    w = out["body"]["week"]
    w["batch"] = {"id": 201, "kind": "friday", "owner": {"id": 1, "name": "Avery Quill"}, "week_start": "2026-11-02",
                  "generated_at": "2026-10-30T16:00:00-05:00"}
    w["batches"] = [w["batch"]]
    w["tasks"] = [{"id": 302, "batch_id": 201, "kind": "followup", "status": "open", "score": 82,
                   "reason": "Key account.", "reasons": ["Key account"], "done_at": None, "snoozed_until": None,
                   "contact": {"id": 21, "name": "Dana Whitlow", "title": "Project Manager", "phone": "913-555-0101",
                               "phone_e164": "+19135550101", "company": {"id": 10, "name": "Prairie Ridge Builders LLC"},
                               "category": "bd", "importance": 3, "confirmed": True}}]
    w["total"] = 1
    return out


def test_a_task_names_its_contact_with_a_link_to_the_contact_page(tmp_path):
    """The contact page has moved (#808): the name, Next up's "Open Dana Whitlow" go there, back to This Week."""
    out = run(tmp_path, me("Avery Quill", "salesperson"),
              responses={"GET /api/bd/week": week_with_dana(), "GET /api/bd/settings": settings()}, name="dana")
    html = out["els"]["lists"]["html"]
    links = re.findall(r'href="(/bd/[^"]*)"', html)
    assert links and set(links) == {"/bd/contact.html?id=21&amp;from=week"}, links
    assert "Open Dana Whitlow" in html

