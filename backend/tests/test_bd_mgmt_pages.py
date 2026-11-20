"""Admin (/bd/admin.html), Potential BD Contacts (/bd/review.html) and Analytics (/bd/analytics.html)
(#809): how each page starts and what it asks the server for, role by role, in node with the tool's
shell stood in for.

Each page reads who this is from the one /api/bd/me answer the sidebar's BD group reads (TWAuth.bdMe),
and what the person may do from its `can`, never from a role name. The `can` maps here are the real
bd/auth.py can(), so the page and the server's map are tested together; what each role should get is
written out by hand from BD's role checks:

  Admin       admin, super admin  People, settings, the phone status, unmatched calls, imports
              assistant           unmatched calls and imports only (nothing admin-only is asked for)
              salesperson         imports only (they import a workbook; Contacts has not moved)
              manager             "Admin isn't part of your BD role." and no request
  Review      every BD role       GET /api/bd/review/candidates?status=all (503 "not built yet" today)
  Analytics   manager, admins     GET /api/bd/contacts (the owners) and GET /api/bd/analytics
              anyone else         "Analytics isn't part of your BD role." and no request
  a refused /api/bd/me: the server's own sentence, and no request, on all three.

Executed by tests/js/bd/bd-page-harness.js. The pages used for real, in Chromium against the live app,
are tests/test_bd_e2e_mgmt.py.
"""
from __future__ import annotations

import html as htmlmod
import json
import pathlib
import re

import pytest

from _node import last_json_line, require_node, run_node
from bd import auth as bd_auth

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "bd" / "bd-page-harness.js"
MORNING = "2026-11-04T09:30:00-06:00"

PEOPLE = {"salesperson": (1, "Avery Quill"), "assistant": (3, "Casey Moret"), "manager": (4, "Devon Hale"),
          "admin": (5, "Emery Stoll"), "super_admin": (6, "Frankie Oduya")}

ADMIN_IDS = ["ad-note", "ad-navbar", "ad-nav", "ad-s-users", "ad-s-friday", "ad-s-rules", "ad-s-lists", "ad-s-phone",
             "ad-s-imports", "ad-users", "ad-friday", "ad-rules", "ad-lists", "ad-phone", "ad-imports", "ad-h-phone",
             "ad-phone-status", "ad-add-jump", "ad-import", "ad-import-file", "ad-attach", "ad-attach-q",
             "ad-attach-results", "ad-attach-status", "ad-attach-outcome", "ad-attach-save", "ad-attach-save-label",
             "ad-attach-save-hint", "ad-attach-yes"]
REVIEW_IDS = ["rv-body", "rv-views"]
ANALYTICS_IDS = ["an-body", "an-tools", "an-sub", "an-export", "an-period", "an-custom", "an-from", "an-to",
                 "an-range-error", "an-owner"]

NOT_BUILT_6 = {"status": 503, "body": {"ok": False, "error": "unavailable", "message": "This part is not built yet (Phase 6)."}}
NOT_BUILT_7 = {"status": 503, "body": {"ok": False, "error": "unavailable", "message": "This part is not built yet (Phase 7)."}}
NO_BD_ROLE = {"status": 403, "body": {"ok": False, "error": "forbidden",
                                      "message": "You don't have a BD role. Ask a BD admin to add you."}}


def ok(body):
    return {"status": 200, "body": dict({"ok": True}, **body)}


def page_scripts(page):
    srcs = re.findall(r'<script src="(/[^"]+)"', (FRONTEND / "bd" / page).read_text(encoding="utf-8"))
    return [s.lstrip("/") for s in srcs if s.startswith("/bd/")]


def me(role):
    uid, name = PEOPLE[role]
    return {"status": 200, "body": {"ok": True, "user": {"id": uid, "name": name, "role": role, "active": True,
                                                         "email": "%s@example.com" % name.lower().replace(" ", ".")},
                                    "can": bd_auth.can({"role": role}), "today": "2026-11-04",
                                    "timezone": "America/Chicago"}}


RESPONSES = {
    "GET /api/bd/admin/users": ok({"items": [{"id": 1, "name": "Avery Quill", "email": "avery.quill@example.com",
                                               "role": "salesperson", "active": True, "last_seen_at": None}],
                                    "total": 1}),
    "GET /api/bd/settings": ok({"settings": {"bd_cadence": "quarterly", "default_frequency": {"maintenance": 3},
                                             "maintenance_touch_days": 120, "weekly_meeting_goal": 5,
                                             "non_dsbc_website_min": 1,
                                             "weekly": {"new_count": 5, "followup_count": 5, "run_day": "friday",
                                                        "run_hour": 16, "enabled": False},
                                             "lead_sources": ["Other/Misc"], "system_lead_sources": [],
                                             "industries": ["Other"], "touch_kinds": ["meeting"]}}),
    "GET /api/bd/admin/telephony": ok({"telephony": {"provider": "null", "connected": False, "last_event_at": None,
                                                     "unmatched_open": 0, "message": "No phone system connected yet."}}),
    "GET /api/bd/admin/unmatched-calls": ok({"items": [], "total": 0}),
    "GET /api/bd/admin/imports": ok({"items": [], "total": 0}),
    "GET /api/bd/review/candidates": NOT_BUILT_6,
    "GET /api/bd/analytics": NOT_BUILT_7,
    "GET /api/bd/contacts": ok({"items": [{"id": 21, "name": "Dana Whitlow", "owner": {"id": 1, "name": "Avery <b>Quill</b>"}}],
                                "total": 1}),
}


def run(tmp_path, page, ids, bd_me, name="s"):
    require_node()
    sc = {"scripts": ["js/crm-core.js"] + page_scripts(page), "token": "tok", "ready": True, "bdMe": bd_me,
          "now": MORNING, "ids": ids, "responses": RESPONSES, "search": "", "pathname": "/bd/" + page}
    f = tmp_path / ("%s.json" % name)
    f.write_text(json.dumps(sc), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = last_json_line(proc.stdout)
    assert out["threw"] is None, out["threw"]
    return out


def asked(out):
    return sorted({"%s %s" % (f["method"], f["url"].split("?")[0]) for f in out["fetches"]})


def text(out, el):
    return htmlmod.unescape(out["els"][el]["text"])


def hidden(out):
    return sorted(i for i in ("ad-s-users", "ad-s-friday", "ad-s-rules", "ad-s-lists", "ad-s-phone", "ad-s-imports")
                  if not out["els"][i]["hidden"])


# ── Admin ───────────────────────────────────────────────────────────────────────────────────────
ADMIN_SHOWN = {
    "admin": ["ad-s-friday", "ad-s-imports", "ad-s-lists", "ad-s-phone", "ad-s-rules", "ad-s-users"],
    "super_admin": ["ad-s-friday", "ad-s-imports", "ad-s-lists", "ad-s-phone", "ad-s-rules", "ad-s-users"],
    "assistant": ["ad-s-imports", "ad-s-phone"],
    "salesperson": ["ad-s-imports"],
    "manager": [],
}
ADMIN_ASKED = {
    "admin": ["GET /api/bd/admin/imports", "GET /api/bd/admin/telephony", "GET /api/bd/admin/unmatched-calls",
              "GET /api/bd/admin/users", "GET /api/bd/settings"],
    "assistant": ["GET /api/bd/admin/imports", "GET /api/bd/admin/unmatched-calls"],
    "salesperson": ["GET /api/bd/admin/imports"],
    "manager": [],
}
ADMIN_ASKED["super_admin"] = ADMIN_ASKED["admin"]


def start_hidden(out):
    """Every section starts hidden in the markup; the harness's stand-in elements start shown, so the
    page must set each one. Reported as the sections left showing."""
    return hidden(out)


@pytest.mark.parametrize("role", list(ADMIN_SHOWN))
def test_admin_shows_and_asks_for_exactly_what_the_role_may_use(tmp_path, role):
    out = run(tmp_path, "admin.html", ADMIN_IDS, me(role), name=role)
    assert asked(out) == ADMIN_ASKED[role]
    if role == "manager":
        assert text(out, "ad-note") == "Admin isn't part of your BD role."
        assert out["els"]["ad-note"]["hidden"] is False
        return
    assert start_hidden(out) == ADMIN_SHOWN[role]
    assert out["els"]["ad-note"]["hidden"] is True or text(out, "ad-note") == ""


def test_the_assistants_phone_section_is_called_unknown_calls(tmp_path):
    out = run(tmp_path, "admin.html", ADMIN_IDS, me("assistant"))
    assert text(out, "ad-h-phone") == "Unknown calls"
    out = run(tmp_path, "admin.html", ADMIN_IDS, me("admin"), name="admin")
    assert text(out, "ad-h-phone") == "", "an admin's keeps the page's own heading"
    assert "Not connected" in text(out, "ad-phone-status")


def test_a_plain_admin_is_offered_no_admin_role_and_the_super_admin_is(tmp_path):
    plain = run(tmp_path, "admin.html", ADMIN_IDS, me("admin"), name="admin")["els"]["ad-users"]["html"]
    assert 'value="admin"' not in plain and 'value="super_admin"' not in plain
    assert "Only a super admin can add an admin." in plain
    sup = run(tmp_path, "admin.html", ADMIN_IDS, me("super_admin"), name="super")["els"]["ad-users"]["html"]
    assert 'value="admin"' in sup and 'value="super_admin"' in sup
    assert "Only a super admin can add an admin." not in sup


# ── Potential BD Contacts ───────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role", list(PEOPLE))
def test_review_asks_every_role_and_says_not_built_yet(tmp_path, role):
    out = run(tmp_path, "review.html", REVIEW_IDS, me(role), name=role)
    assert [f["url"] for f in out["fetches"]] == ["/api/bd/review/candidates?status=all"]
    assert "This part is not built yet (Phase 6)." in text(out, "rv-body")
    assert "Try again" in text(out, "rv-body")


# ── Analytics ───────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role", ["manager", "admin", "super_admin"])
def test_analytics_asks_for_the_owners_and_the_year_for_the_roles_allowed(tmp_path, role):
    out = run(tmp_path, "analytics.html", ANALYTICS_IDS, me(role), name=role)
    assert [f["url"] for f in out["fetches"]] == ["/api/bd/contacts?limit=500",
                                                  "/api/bd/analytics?from=2026-01-01&to=2026-11-04"]
    assert "This part is not built yet (Phase 7)." in text(out, "an-body")
    assert text(out, "an-sub") == "Jan 1 - Wed, Nov 4, 2026"
    assert out["els"]["an-tools"]["hidden"] is False
    owners = out["els"]["an-owner"]["html"]
    assert '<option value="1">Avery &lt;b&gt;Quill&lt;/b&gt;</option>' in owners, "an owner's name goes in as text"


@pytest.mark.parametrize("role", ["salesperson", "assistant"])
def test_analytics_is_not_part_of_the_other_roles(tmp_path, role):
    out = run(tmp_path, "analytics.html", ANALYTICS_IDS, me(role), name=role)
    assert out["fetches"] == []
    assert text(out, "an-body") == "Analytics isn't part of your BD role."


# ── a refused /api/bd/me ────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("page, ids, box", [("admin.html", ADMIN_IDS, "ad-note"), ("review.html", REVIEW_IDS, "rv-body"),
                                            ("analytics.html", ANALYTICS_IDS, "an-body")])
def test_a_person_with_no_bd_role_gets_the_servers_sentence_and_no_request(tmp_path, page, ids, box):
    out = run(tmp_path, page, ids, NO_BD_ROLE)
    assert out["fetches"] == []
    assert text(out, box) == "You don't have a BD role. Ask a BD admin to add you."
