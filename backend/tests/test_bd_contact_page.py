"""One contact (/bd/contact.html) and Add a contact (/bd/add.html) (#808): how each page starts and what
it offers whom, in node, with the tool's shell stood in for.

Both pages read who this is from the one /api/bd/me answer the sidebar's BD group reads
(TWAuth.bdMe), and what the person may do from its `can`, never from a role name. The `can` maps
here are the real bd/auth.py can(), so the page and the server's map are tested together; what each
role should see is written out by hand:

  * a refused /api/bd/me: the server's own sentence and no data, no request;
  * the contact page, contact 21 (Dana Whitlow), whose history holds a call Avery logged (101), a
    call the phone system logged (104, nobody's) and an email Blair logged (105):
      salesperson Avery   Call, Log, a note; Edit on her own call only; no Delete
      assistant Casey     no Call; a note, Edit details and Archive; nothing to edit in History
      manager Devon       no Call, Log, note or Archive; "Edit follow-up cadence"; the priority score
      admin Emery         Edit and Delete on every entry; the priority score (can.pick_owner)
  * the company name links to its account on Contacts (?company=), and Back goes to Contacts unless the
    person came from This Week (#810: Contacts has moved; BD's own links come back);
    Back is to This Week only for a person who came from it;
  * Add a contact: a person whose can has no add_contact (the manager) is told so and gets no form;
    the others get the form, with Cancel going to /bd/;
  * every request is under /api/bd/, and every value goes in as text.

Executed by tests/js/bd/bd-page-harness.js. The pages used for real, in Chromium against the live
app, are tests/test_bd_e2e_contact.py.
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
          "admin": (5, "Emery Stoll")}


def page_scripts(page):
    srcs = re.findall(r'<script src="(/[^"]+)"', (FRONTEND / "bd" / page).read_text(encoding="utf-8"))
    return [s.lstrip("/") for s in srcs if s.startswith("/bd/")]


def me(role):
    uid, name = PEOPLE[role]
    return {"status": 200, "body": {"ok": True, "user": {"id": uid, "name": name, "role": role, "active": True,
                                                         "email": "%s@example.com" % name.lower().replace(" ", ".")},
                                    "can": bd_auth.can({"role": role}), "today": "2026-11-04",
                                    "timezone": "America/Chicago"}}


def run(tmp_path, page, ids, bd_me, search="", responses=None, name="s"):
    require_node()
    sc = {"scripts": ["js/crm-core.js"] + page_scripts(page), "token": "tok", "ready": True, "bdMe": bd_me,
          "now": MORNING, "ids": ids, "responses": responses or {}, "search": search,
          "pathname": "/bd/" + page}
    f = tmp_path / ("%s.json" % name)
    f.write_text(json.dumps(sc), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = last_json_line(proc.stdout)
    assert out["threw"] is None, out["threw"]
    return out


def text(out, el):
    """What the element reads as, entities read (the harness keeps the text as the markup spells it)."""
    return htmlmod.unescape(out["els"][el]["text"])


def ok(body):
    return {"status": 200, "body": dict({"ok": True}, **body)}


# ── the contact page ────────────────────────────────────────────────────────────────────────────
def dana(name="Dana Whitlow"):
    return {"id": 21, "name": name, "title": "Project Manager", "company": {"id": 10, "name": "Prairie Ridge Builders LLC"},
            "city": "Overland Park", "email": "dana.whitlow@prairieridge.example.com", "phone": "913-555-0101",
            "phone_e164": "+19135550101", "category": "bd", "confirmed": True, "importance": 3,
            "owner": {"id": 1, "name": "Avery Quill"}, "co_owner": None, "industry": "General contractor",
            "lead_source": "Referral", "stage": "Bidding", "tags": [], "notes": None, "archived_at": None,
            "duplicate_of": None, "next_step": "Send the epoxy sample board", "next_step_date": "2026-11-06",
            "promised_date": "2026-11-05", "last_live_at": "2026-10-20T10:00:00-05:00", "next_due_date": "2026-11-20",
            "frequency_per_year": 12, "touches_this_year": 1, "cadence_status": "behind", "cadence": "monthly",
            "cadence_source": "global", "cadence_override": None, "cadence_override_until": None}


def entry(iid, kind, outcome, user, summary, at):
    return {"type": "interaction", "at": at, "interaction": {
        "id": iid, "contact_id": 21, "kind": kind, "direction": "out", "outcome": outcome,
        "counts_as_touch": outcome == "answered", "occurred_at": at, "duration_s": 420 if outcome == "answered" else 0,
        "summary": summary, "transcript": None, "recording_url": None, "provider": "manual", "external_id": None,
        "user": user}}


HISTORY = [
    entry(105, "email", None, {"id": 2, "name": "Blair Fenn"}, "Sent the coating options.", "2026-10-28T08:00:00-05:00"),
    entry(104, "call", "no_answer", None, "", "2026-10-25T12:00:00-05:00"),
    entry(101, "call", "answered", {"id": 1, "name": "Avery Quill"}, "Talked through the spring floor schedule.",
          "2026-10-20T10:00:00-05:00"),
]
TASK = {"id": 302, "status": "open", "kind": "followup", "score": 82, "reasons": ["Key account"]}


def contact_responses(name="Dana Whitlow"):
    return {
        "GET /api/bd/contacts/21": ok({"contact": dana(name), "open_task": TASK, "pending_recommendation": None,
                                       "missed_call": None}),
        "GET /api/bd/contacts/21/interactions": ok({"items": HISTORY}),
        "GET /api/bd/settings": ok({"settings": {"ai_enabled": False, "bd_cadence": "monthly"}}),
        "GET /api/bd/companies/10": ok({"company": {"id": 10, "name": "Prairie Ridge Builders LLC"}, "contacts": []}),
    }


def contact_page(tmp_path, role, search="?id=21", name=None, responses=None):
    out = run(tmp_path, "contact.html", ["cd-root"], me(role), search=search,
              responses=contact_responses() if responses is None else responses, name=name or role)
    return out, out["els"]["cd-root"]["html"]


def acts(html, act):
    return re.findall(r'data-act="%s" data-entry="(\d+)"' % act, html)


def test_the_contact_page_runs_the_bd_shell_then_the_call_sheet_then_the_page():
    assert page_scripts("contact.html") == ["bd/js/bd-api.js", "bd/js/bd-shared.js", "bd/js/bd-core.js",
                                            "bd/js/bd-call.js", "bd/js/bd-contact.js"]
    assert page_scripts("add.html") == ["bd/js/bd-api.js", "bd/js/bd-shared.js", "bd/js/bd-core.js", "bd/js/bd-add.js"]


def test_a_salesperson_calls_logs_notes_and_edits_only_her_own_entry(tmp_path):
    out, html = contact_page(tmp_path, "salesperson")
    assert 'data-act="call"' in html and 'href="tel:+19135550101"' in html
    assert 'data-act="log-menu"' in html and 'id="cd-note"' in html and 'data-act="archive"' in html
    assert acts(html, "entry-edit") == ["101"], "her own call only: not Blair's email, not the phone system's call"
    assert acts(html, "entry-delete") == []
    assert "Priority 82" not in html, "the score is the manager's"


def test_an_assistant_adds_a_note_but_has_no_way_to_log_a_call(tmp_path):
    out, html = contact_page(tmp_path, "assistant")
    assert 'data-act="call"' not in html, "no Call button"
    assert 'id="cd-note"' in html, "the note box"
    assert 'data-act="edit"' in html and "Edit details" in html and 'data-act="archive"' in html
    assert acts(html, "entry-edit") == [] and acts(html, "entry-delete") == []
    assert "log-sent" not in html


def test_a_manager_reads_and_changes_only_the_cadence(tmp_path):
    out, html = contact_page(tmp_path, "manager")
    for hook in ('data-act="call"', 'data-act="log-menu"', 'id="cd-note"', 'data-act="archive"',
                 'data-act="step-change"', 'data-act="confirm-toggle"', "Edit details"):
        assert hook not in html, hook
    assert "Edit follow-up cadence" in html
    assert "Priority 82 this week" in html
    assert acts(html, "entry-edit") == [] and acts(html, "entry-delete") == []


def test_a_bd_admin_edits_and_deletes_any_entry(tmp_path):
    out, html = contact_page(tmp_path, "admin")
    assert sorted(acts(html, "entry-edit")) == ["101", "104", "105"]
    assert sorted(acts(html, "entry-delete")) == ["101", "104", "105"]
    assert 'aria-label="Delete: Call, Tue, Oct 20, 7 min"' in html, "each button names its entry"


@pytest.mark.parametrize("role, shown", [("salesperson", False), ("assistant", False), ("manager", True),
                                         ("admin", True)])
def test_the_priority_score_shows_to_whoever_may_pick_a_week_as_on_this_week(tmp_path, role, shown):
    """The score is This Week's (can.pick_owner, bd-week.js): the manager and a BD admin see it, the
    salesperson and the assistant do not. Not worked out from edit_contact or a role name."""
    out, html = contact_page(tmp_path, role)
    assert ("Priority 82 this week" in html) is shown, role


def test_the_company_opens_its_account_on_contacts_and_back_goes_to_contacts(tmp_path):
    """#810: Contacts has moved, so BD's links come back: the company opens its account there
    (/bd/contacts.html?company=10) and Back, for a person who did not come from This Week, is Contacts."""
    out, html = contact_page(tmp_path, "salesperson")
    assert re.search(r'<a class="cd-company" href="/bd/contacts\.html\?company=10">Prairie Ridge Builders LLC</a>', html), \
        html[:600]
    links = re.findall(r'href="([^"]+)"', html)
    assert links and all(h.startswith(("tel:", "mailto:", "sms:", "/bd/")) for h in links), links
    assert re.search(r'<a class="back-link cd-back" href="/bd/contacts\.html">.*Contacts</a>', html), html[:400]


def test_from_this_week_back_goes_to_this_week(tmp_path):
    out, html = contact_page(tmp_path, "salesperson", search="?id=21&from=week", name="from-week")
    assert re.search(r'<a class="back-link cd-back" href="/bd/">.*This Week</a>', html), html[:400]
    out, html = contact_page(tmp_path, "assistant", search="?id=21&from=week", name="assistant-from-week")
    assert re.search(r'<a class="back-link cd-back" href="/bd/contacts\.html">.*Contacts</a>', html), \
        "no This Week for a role without one: her Back is Contacts, her BD home"


def test_every_request_is_under_api_bd(tmp_path):
    out, _html = contact_page(tmp_path, "salesperson")
    urls = sorted({f["url"].split("?")[0] for f in out["fetches"]})
    assert urls == ["/api/bd/companies/10", "/api/bd/contacts/21", "/api/bd/contacts/21/interactions",
                    "/api/bd/settings"], urls
    assert ("GET", "/api/bd/me") not in [(f["method"], f["url"]) for f in out["fetches"]]


def test_a_refused_bd_login_sees_the_sentence_and_no_data(tmp_path):
    refused = {"status": 403, "body": {"ok": False, "error": "forbidden",
                                       "message": "You don't have a BD role. Ask a BD admin to add you."}}
    out = run(tmp_path, "contact.html", ["cd-root"], refused, search="?id=21", responses=contact_responses())
    assert "You don't have a BD role. Ask a BD admin to add you." in text(out, "cd-root")
    assert out["fetches"] == []


def test_a_contact_id_that_is_not_a_number_is_not_found_without_a_request(tmp_path):
    out, html = contact_page(tmp_path, "salesperson", search="?id=21x", name="bad-id")
    assert "That contact isn" in text(out, "cd-root")
    # BD's "Back to Contacts" again (#810; #808 sent it to /bd/ while Contacts had not moved)
    assert '<a class="btn btn-primary" href="/bd/contacts.html">Back to Contacts</a>' in html
    assert [f for f in out["fetches"] if "/contacts/" in f["url"]] == []


def test_values_go_in_as_text(tmp_path):
    hostile = "<img src=x onerror=alert(1)>"
    out, html = contact_page(tmp_path, "admin", responses=contact_responses(hostile), name="hostile")
    assert "<img" not in html and "&lt;img" in html


def test_an_email_link_carries_the_address_and_nothing_after_it(tmp_path):
    """The server only length-checks an email, so one stored with a query (through the API or an
    import) must not open the mail app with a hidden copy or a written body: both Email links stop at
    the address."""
    responses = contact_responses()
    c = responses["GET /api/bd/contacts/21"]["body"]["contact"]
    c["email"] = "dana.whitlow@prairieridge.example.com?bcc=someone@other.example.com&body=Hi"
    out, html = contact_page(tmp_path, "salesperson", responses=responses)
    mailto = re.findall(r'href="(mailto:[^"]*)"', html)
    assert mailto == ["mailto:dana.whitlow@prairieridge.example.com"] * 2, mailto


# ── Add a contact ───────────────────────────────────────────────────────────────────────────────
ADD_IDS = ["add-root", "add-form", "add-company", "add-company-list", "add-company-check", "add-phone", "add-email",
           "add-pills", "add-confirm", "add-name"]


def add_responses():
    users = [{"id": 1, "name": "Avery Quill", "role": "salesperson"}, {"id": 2, "name": "Blair Fenn", "role": "salesperson"},
             {"id": 3, "name": "Casey Moret", "role": "assistant"}]
    return {"GET /api/bd/settings": ok({"settings": {"bd_cadence": "quarterly"}}),
            "GET /api/bd/users": ok({"total": 3, "items": users})}


def test_a_manager_is_told_adding_is_not_part_of_the_role_and_gets_no_form(tmp_path):
    out = run(tmp_path, "add.html", ADD_IDS, me("manager"), responses=add_responses(), name="add-manager")
    root = out["els"]["add-root"]
    assert "Adding contacts isn't part of your BD role." in text(out, "add-root")
    assert 'id="add-form"' not in root["html"]
    assert out["fetches"] == []


def test_a_refused_bd_login_gets_the_sentence_on_add(tmp_path):
    refused = {"status": 503, "body": {"ok": False, "error": "unavailable", "message": "The BD CRM is not turned on."}}
    out = run(tmp_path, "add.html", ADD_IDS, refused, responses=add_responses(), name="add-refused")
    assert "The BD CRM is not turned on." in text(out, "add-root")
    assert out["fetches"] == []


def test_the_assistant_and_the_salesperson_get_the_form(tmp_path):
    for role in ("assistant", "salesperson"):
        out = run(tmp_path, "add.html", ADD_IDS, me(role), responses=add_responses(), name="add-" + role)
        html = out["els"]["add-root"]["html"]
        assert 'id="add-form"' in html, role
        assert sorted({f["url"].split("?")[0] for f in out["fetches"]}) == ["/api/bd/settings", "/api/bd/users"]
        # #810: BD's own links come back now that Contacts has moved: "Contacts" above, Cancel to it.
        assert '<a class="btn btn-tertiary" href="/bd/contacts.html">Cancel</a>' in html
        assert '<a class="back-link add-back" href="/bd/contacts.html">' in html and "<span>Contacts</span></a>" in html, \
            html[:300]
    # The owner list starts on the salesperson adding (Blair, the second listed), not on the first one.
    blair = me("salesperson")
    blair["body"]["user"].update({"id": 2, "name": "Blair Fenn"})
    out = run(tmp_path, "add.html", ADD_IDS, blair, responses=add_responses(), name="add-owner")
    html = out["els"]["add-root"]["html"]
    assert '<option value="2" selected>Blair Fenn</option>' in html
    out = run(tmp_path, "add.html", ADD_IDS, me("assistant"), responses=add_responses(), name="add-owner-2")
    assert '<option value="1" selected>Avery Quill</option>' in out["els"]["add-root"]["html"], \
        "an assistant starts on the first salesperson"
