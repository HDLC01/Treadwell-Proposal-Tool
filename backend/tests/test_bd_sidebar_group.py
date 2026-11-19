"""The BD CRM row is a collapsible group in the sidebar (#806; Q5 as changed by Hanz on 2026-11-19).

There is no BD sub nav under the top bar. The BD sections sit indented under the BD CRM row, in the
sidebar (and so in the phone drawer, and under the sidebar's Hide menu):

  * a chevron button beside the row opens and shuts them, with aria-expanded and aria-controls;
  * the group is open on every /bd/ page and starts shut elsewhere; on desktop the last choice is
    remembered (tw_bd_open, like the sidebar's own tw_nav_open), and never on a phone;
  * a section shows only when BD's can() map (from /api/bd/me) allows it for the person's BD role,
    and only once its page has moved (in this ticket only This Week, the BD home page);
  * the current section is lit by the page's full path.

Executed: js/bd-sidebar-group-harness.js runs the real auth.js init() with the tool's /api/me and
BD's /api/bd/me answering, and the `can` maps come from the real bd/auth.py can().
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest

from _node import last_json_line, require_node, run_node
from bd import auth as bd_auth

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "bd-sidebar-group-harness.js"

ME = {"ok": True, "email": "marisol@wetreadwell.com", "name": "Marisol Quint", "role": "admin",
      "status": "active", "nav_denied": [], "nav_denied_pages": {}, "grants": [], "nav_off": []}


def bd_me(role):
    """BD's /api/bd/me for a person with this BD role, `can` from the real can()."""
    return {"status": 200, "body": {"ok": True, "user": {"id": 1, "name": "Marisol Quint",
                                                         "role": role},
                                    "can": bd_auth.can({"role": role}), "today": "2026-11-04",
                                    "timezone": "America/Chicago"}}


NO_BD_ROLE = {"status": 403, "body": {"ok": False, "error": "forbidden",
                                      "message": "You don't have a BD role. Ask a BD admin."}}


def run(tmp_path, pathname, wide=True, storage=None, me=None, bd=None, clicks=(), name="s"):
    require_node()
    sc = {"pathname": pathname, "wide": wide, "storage": storage or {}, "me": me or ME,
          "bdMe": bd_me("salesperson") if bd is None else bd, "clicks": list(clicks)}
    f = tmp_path / ("%s.json" % name)
    f.write_text(json.dumps(sc), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f)
    assert proc.returncode == 0, "the harness failed:\n" + proc.stderr
    out = last_json_line(proc.stdout)
    assert "/portal.html" in out["rows"], "vacuity: no sidebar was drawn"
    return out


def bd_fetches(out):
    return [u for u in out["fetches"] if "/api/bd/me" in u]


# ── the chevron and where the group lives ────────────────────────────────────
def test_the_chevron_is_a_real_button_naming_the_list_it_controls(tmp_path):
    out = run(tmp_path, "/bd/")
    assert out["groupInMarkup"] and out["insideSidebar"], (
        "the BD sections must sit inside the sidebar's nav, so the drawer and Hide menu carry them")
    assert out["markup"]["type"] == "button"
    assert out["markup"]["controls"] == "tw-bd-sections"
    s = out["states"][0]
    assert s["expanded"] == "true" and s["hidden"] is False


@pytest.mark.parametrize("page", ["/bd/", "/bd/index.html", "/bd/contacts.html", "/bd/admin.html"])
def test_the_group_is_open_on_every_bd_page(tmp_path, page):
    out = run(tmp_path, page)
    assert out["markup"]["expanded"] == "true" and out["markup"]["hidden"] is False
    assert out["states"][0]["expanded"] == "true"
    assert out["lit"] == ["/bd/"], "only the BD CRM row is lit on a BD page"


def test_the_group_is_open_on_a_bd_page_even_after_it_was_shut_elsewhere(tmp_path):
    out = run(tmp_path, "/bd/", storage={"tw_bd_open": "0"})
    assert out["states"][0]["expanded"] == "true"


@pytest.mark.parametrize("wide", [True, False])
def test_the_group_starts_shut_elsewhere_and_asks_bd_nothing(tmp_path, wide):
    out = run(tmp_path, "/portal.html", wide=wide)
    assert "/bd/" in out["rows"]
    assert out["markup"]["expanded"] == "false" and out["markup"]["hidden"] is True
    s = out["states"][0]
    assert s["expanded"] == "false" and s["hidden"] is True and s["sections"] == []
    assert bd_fetches(out) == [], "a shut group must not cost every tool page a BD request"


def test_the_chevron_opens_and_shuts_it_and_desktop_remembers(tmp_path):
    out = run(tmp_path, "/portal.html", clicks=["chev", "chev"])
    shut, opened, shut_again = out["states"]
    assert shut["expanded"] == "false" and shut["hidden"] is True
    assert opened["expanded"] == "true" and opened["hidden"] is False
    assert opened["storage"].get("tw_bd_open") == "1"
    assert [s["href"] for s in opened["sections"]] == ["/bd/"]
    assert shut_again["expanded"] == "false" and shut_again["hidden"] is True
    assert shut_again["storage"].get("tw_bd_open") == "0"
    assert len(bd_fetches(out)) == 1, "BD is asked once per page, not on every open"


def test_desktop_reopens_it_where_it_was_left_open(tmp_path):
    out = run(tmp_path, "/projects.html", storage={"tw_bd_open": "1"})
    assert out["states"][0]["expanded"] == "true"
    assert [s["href"] for s in out["states"][0]["sections"]] == ["/bd/"]


def test_a_phone_never_reads_or_writes_the_remembered_choice(tmp_path):
    out = run(tmp_path, "/projects.html", wide=False, storage={"tw_bd_open": "1"},
              clicks=["chev", "chev"])
    first, opened, shut = out["states"]
    assert first["expanded"] == "false", "a desktop choice leaked onto a phone"
    assert opened["expanded"] == "true"
    assert opened["storage"] == {"tw_bd_open": "1"} and shut["storage"] == {"tw_bd_open": "1"}


def test_on_a_phone_the_group_is_open_on_a_bd_page_inside_the_drawer(tmp_path):
    out = run(tmp_path, "/bd/", wide=False)
    assert out["insideSidebar"]
    assert out["states"][0]["expanded"] == "true"
    assert out["states"][0]["navOpen"] is False, "the drawer itself still starts shut on a phone"


def test_tapping_a_section_in_the_phone_drawer_shuts_the_drawer(tmp_path):
    out = run(tmp_path, "/bd/", wide=False, clicks=["burger", "section"])
    shut, opened, tapped = out["states"]
    assert shut["navOpen"] is False and opened["navOpen"] is True, "vacuity: the drawer never opened"
    assert tapped["navOpen"] is False


# ── which sections show ──────────────────────────────────────────────────────
# Only This Week (the BD home page) has moved in this ticket. Expected by hand from BD's own rules
# (bd/auth.py can(): week = salesperson, manager, admin, super admin), not by running a rule here.
SECTIONS_BY_ROLE = {
    "salesperson": ["/bd/"],
    "assistant": [],
    "manager": ["/bd/"],
    "admin": ["/bd/"],
    "super_admin": ["/bd/"],
}


@pytest.mark.parametrize("role", list(SECTIONS_BY_ROLE))
def test_the_sections_are_exactly_the_ones_can_allows(tmp_path, role):
    out = run(tmp_path, "/bd/", bd=bd_me(role), name=role)
    s = out["states"][0]
    assert [x["href"] for x in s["sections"]] == SECTIONS_BY_ROLE[role]
    if not SECTIONS_BY_ROLE[role]:
        assert s["note"], "an open group with nothing in it says why"


def test_this_week_is_lit_by_its_full_path(tmp_path):
    for page in ("/bd/", "/bd/index.html"):
        s = run(tmp_path, page, name=page.strip("/").replace("/", "_") or "root")["states"][0]
        assert s["sections"] == [{"href": "/bd/", "label": "This Week", "active": True,
                                  "current": True}], page
    s = run(tmp_path, "/bd/contacts.html", name="contacts")["states"][0]
    assert s["sections"][0]["active"] is False and s["sections"][0]["current"] is False
    s = run(tmp_path, "/index.html", storage={"tw_bd_open": "1"}, name="tool-index")["states"][0]
    assert s["sections"][0]["active"] is False, "the tool's own index.html is not BD's This Week"


def test_no_bd_role_shows_no_section_and_says_so_in_bd_s_words(tmp_path):
    s = run(tmp_path, "/bd/", bd=NO_BD_ROLE)["states"][0]
    assert s["sections"] == []
    assert s["note"] == "You don&#39;t have a BD role. Ask a BD admin.", "escaped, BD's own sentence"


def test_a_refusal_with_no_sentence_still_says_why(tmp_path):
    s = run(tmp_path, "/bd/", bd={"status": 403, "body": {}})["states"][0]
    assert s["sections"] == [] and s["note"] == "You don&#39;t have a BD role."


def test_bd_s_sentence_is_escaped(tmp_path):
    s = run(tmp_path, "/bd/", bd={"status": 403, "body": {
        "ok": False, "error": "forbidden", "message": "<img src=x onerror=alert(1)>"}})["states"][0]
    assert s["note"] == "&lt;img src=x onerror=alert(1)&gt;"


def test_bd_not_answering_shows_no_section(tmp_path):
    s = run(tmp_path, "/bd/", bd={"status": 503, "body": {"ok": False, "error": "unavailable",
                                                         "message": "The BD CRM is not turned on."}}
            )["states"][0]
    assert s["sections"] == [] and s["note"]


def test_the_row_switched_off_takes_the_whole_group_with_it(tmp_path):
    out = run(tmp_path, "/portal.html", me=dict(ME, nav_off=["/bd/"]), storage={"tw_bd_open": "1"})
    assert "/bd/" not in out["rows"]
    assert out["groupInMarkup"] is False
    assert bd_fetches(out) == []


def test_the_row_denied_by_policy_takes_the_whole_group_with_it(tmp_path):
    me = dict(ME, role="user", nav_denied=["/bd/"])
    out = run(tmp_path, "/projects.html", me=me, storage={"tw_bd_open": "1"})
    assert "/bd/" not in out["rows"] and out["groupInMarkup"] is False
    assert bd_fetches(out) == []


def test_a_section_is_listed_only_once_its_page_has_moved():
    """The registry names only moved pages. Contacts, Add contact, Potential BD Contacts, Analytics
    and Admin join it in the tickets that move their pages."""
    src = (FRONTEND / "auth.js").read_text(encoding="utf-8")
    block = src[src.index("const BD_SECTIONS = ["):]
    block = block[:block.index("];")]
    assert re.findall(r'href:\s*"([^"]+)"', block) == ["/bd/"]
