"""The Contacts page (/bd/contacts.html, #810): how it starts, role by role, and what it draws from the
account list, in node with the tool's shell stood in for (tests/js/bd/bd-page-harness.js).

The page reads who this is from the one /api/bd/me answer the sidebar's BD group reads, and what the
person may do from its `can`, never from a role name. The `can` maps here are the real bd/auth.py can(),
so the page and the server's map are tested together. What each role should get, by hand from BD's
own Contacts page and the 2026-11-20 decisions on #810:

  every BD role     both tabs' accounts (GET /api/bd/contacts/accounts, BD and Maintenance)
  import            the Import button (a salesperson, the assistant, the admins); "Past imports" in its
                    menu, and the last import's day, only for someone the Admin page opens for
                    (admin_area), so a salesperson is never sent to a page that refuses them
  add_contact       Add contact, and "Add someone here" in an opened account
  admin_area        To tidy this Friday, with the unknown calls (GET /api/bd/admin/unmatched-calls)
  move_company      the "..." button on each company row (Q5: never the assistant)
  merge_companies   the likely duplicate BD accounts (#811, Q21, Q36: the assistant and the admins):
                    GET /api/bd/contacts/accounts/duplicates, the "Same account?" notes and Recently
                    merged on the Possible duplicates filter, and the pairs in To tidy's count

The data is made up, shaped like the fixture seed's (bd/ops/fixture_seed.py), on its Wednesday,
2026-11-04: Bluestem Logistics (3 BD people; Avery and Blair, the two salespeople there, tie: Avery
shown, "+1", no live talk yet),
Prairie Ridge Builders LLC (Dana, an answered call Tue, Oct 20) and, on the Maintenance tab, Kaw Valley
Cold Storage (Hal and Nora; Hal's answered call Thu, Aug 20). The search answers are the contract's
shapes (docs/bd/api-contract.md, "GET /api/bd/contacts/search"). The page used for real, in Chromium
against the live app, is tests/test_bd_e2e_contacts.py.
"""
from __future__ import annotations

import copy
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

IDS = ["ct-note", "ct-sub", "ct-import", "ct-import-file", "ct-add", "ct-tidy", "ct-tidy-cards", "ct-unknown",
       "ct-tab-bd", "ct-tab-maintenance", "ct-tools", "ct-q", "ct-sort", "ct-chips", "ct-count", "ct-dupes", "ct-list"]

AVERY = {"id": 1, "name": "Avery Quill"}
BLAIR = {"id": 2, "name": "Blair Fenn"}
DEVON = {"id": 4, "name": "Devon Hale"}


def person(pid, name, owner, **kw):
    p = {"id": pid, "name": name, "title": "", "phone": None, "phone_e164": None, "email": None, "category": "bd",
         "confirmed": True, "importance": 1, "owner": owner, "duplicate_of": None, "lead_source": "Other/Misc",
         "last_live_at": None, "last_followup_at": None, "cadence_status": "never", "cadence": "quarterly",
         "cadence_source": "global", "cadence_override_until": None, "maintenance_due": False,
         "maintenance_due_date": None}
    p.update(kw)
    return p


BLUESTEM = {"id": 16, "name": "Bluestem Logistics", "city": "Lenexa", "industry": "Warehousing", "category": "bd",
            "people_count": 3, "owner": AVERY, "other_owners": 1, "last_live_at": None, "people": [
                person(29, "Ines Varga", DEVON, title="Purchasing", phone="913-555-0109", phone_e164="+19135550109",
                       email="ines.varga@bluestem.example.com", confirmed=False),
                person(27, "Lena Ortiz", AVERY, title="Operations Manager", importance=3, cadence="monthly",
                       cadence_source="override", cadence_override_until="2026-12-31"),
                person(28, "Sam Achebe", BLAIR, title="Facilities", phone="913-555-0108", phone_e164="+19135550108",
                       email="sam.achebe@bluestem.example.com")]}
PRAIRIE = {"id": 10, "name": "Prairie Ridge <b>Builders</b> LLC", "city": "Overland Park",
           "industry": "General contractor", "category": "bd", "people_count": 1, "owner": AVERY, "other_owners": 0,
           "last_live_at": "2026-10-20T10:00:00-05:00", "people": [
               person(21, "Dana Whitlow", AVERY, title="Project Manager", phone="913-555-0101",
                      phone_e164="+19135550101", email="dana.whitlow@prairieridge.example.com",
                      last_live_at="2026-10-20T10:00:00-05:00", cadence_status="on_track")]}
KAW = {"id": 17, "name": "Kaw Valley Cold Storage", "city": "Lawrence", "industry": "Cold storage",
       "category": "maintenance", "people_count": 2, "owner": AVERY, "other_owners": 0,
       "last_live_at": "2026-08-20T10:00:00-05:00", "people": [
           person(30, "Hal Brecken", AVERY, category="maintenance", maintenance_due_date="2026-12-18",
                  last_followup_at="2026-08-20T10:00:00-05:00", last_live_at="2026-08-20T10:00:00-05:00"),
           person(31, "Nora Lindqvist", AVERY, category="maintenance", maintenance_due=True)]}

CALL = {"id": 801, "from_e164": "+19135550199", "direction": "in", "occurred_at": "2026-11-03T16:42:00-06:00",
        "duration_s": 95, "summary": "Asked about a quote", "status": "open"}


def ok(body):
    return {"status": 200, "body": dict({"ok": True}, **body)}


def responses(search=None):
    r = {
        "GET /api/bd/contacts/accounts": None,        # answered by category, below
        "GET /api/bd/admin/unmatched-calls": ok({"items": [CALL], "total": 1}),
        "GET /api/bd/admin/imports": ok({"items": [{"id": 1, "file_name": "made-up.csv",
                                                      "started_at": "2026-10-01T10:00:00-05:00"}], "total": 1}),
    }
    if search is not None:
        r["GET /api/bd/contacts/search"] = ok(search)
    return r


def me(role):
    uid, name = PEOPLE[role]
    return {"status": 200, "body": {"ok": True, "user": {"id": uid, "name": name, "role": role, "active": True,
                                                         "email": "%s@example.com" % name.lower().replace(" ", ".")},
                                    "can": bd_auth.can({"role": role}), "today": "2026-11-04",
                                    "timezone": "America/Chicago"}}


def page_scripts():
    srcs = re.findall(r'<script src="(/[^"]+)"', (FRONTEND / "bd" / "contacts.html").read_text(encoding="utf-8"))
    return [s.lstrip("/") for s in srcs if s.startswith("/bd/")]


def run(tmp_path, bd_me, search="", search_answer=None, bd=None, maint=None, name="s", dupes=None):
    """The page, started as `bd_me`, at contacts.html`search`. The harness answers a route by its path,
    so the two tabs' answers are told apart by a stand-in that the page's own category picks. `dupes`
    is the duplicates route's whole answer ({status, body}); left out, that route is not there (404)."""
    require_node()
    res = responses(search_answer)
    if dupes is not None:
        res["GET /api/bd/contacts/accounts/duplicates"] = dupes
    bd_items = [PRAIRIE, BLUESTEM] if bd is None else bd
    m_items = [KAW] if maint is None else maint
    res.pop("GET /api/bd/contacts/accounts")
    sc = {"scripts": ["js/crm-core.js"] + page_scripts(), "token": "tok", "ready": True, "bdMe": bd_me,
          "now": MORNING, "ids": IDS, "responses": res, "search": search, "pathname": "/bd/contacts.html",
          "byQuery": {"GET /api/bd/contacts/accounts": {
              "category=bd": ok({"category": "bd", "total": len(bd_items), "items": bd_items}),
              "category=maintenance": ok({"category": "maintenance", "total": len(m_items), "items": m_items})}}}
    f = tmp_path / ("%s.json" % name)
    f.write_text(json.dumps(sc), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f)
    assert proc.returncode == 0, proc.stderr[-3000:]
    out = last_json_line(proc.stdout)
    assert out["threw"] is None, out["threw"]
    return out


def asked(out):
    return sorted("%s %s" % (f["method"], f["url"]) for f in out["fetches"])


def text(out, el):
    return " ".join(htmlmod.unescape(out["els"][el]["text"]).split())


def markup(out, el):
    return out["els"][el]["html"]


def shown(out, el):
    return not out["els"][el]["hidden"]


ACCOUNTS = ["GET /api/bd/contacts/accounts?category=bd&limit=500&offset=0",
            "GET /api/bd/contacts/accounts?category=maintenance&limit=500&offset=0"]
TIDY = ["GET /api/bd/admin/imports?limit=1", "GET /api/bd/admin/unmatched-calls"]
DUPES = ["GET /api/bd/contacts/accounts/duplicates?limit=500&offset=0"]
ASKED = {
    "salesperson": ACCOUNTS,
    "assistant": sorted(ACCOUNTS + TIDY + DUPES),
    "manager": ACCOUNTS,
    "admin": sorted(ACCOUNTS + TIDY + DUPES),
    "super_admin": sorted(ACCOUNTS + TIDY + DUPES),
}
# (Import, Add contact, To tidy, the "..." menu): by hand from BD's role checks and Q5.
CONTROLS = {
    "salesperson": (True, True, False, True),
    "assistant": (True, True, True, False),
    "manager": (False, False, False, True),
    "admin": (True, True, True, True),
    "super_admin": (True, True, True, True),
}


# ── who gets what ─────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("role", list(ASKED))
def test_each_role_asks_for_exactly_what_it_may_use(tmp_path, role):
    out = run(tmp_path, me(role), name=role)
    assert asked(out) == ASKED[role]


@pytest.mark.parametrize("role", list(CONTROLS))
def test_each_role_sees_exactly_its_controls(tmp_path, role):
    out = run(tmp_path, me(role), name=role)
    imp, add, tidy, menu = CONTROLS[role]
    assert (shown(out, "ct-import"), shown(out, "ct-add"), shown(out, "ct-tidy")) == (imp, add, tidy)
    # one "..." per company row on the tab (two BD accounts), or none
    assert markup(out, "ct-list").count("data-more") == (2 if menu else 0)


def test_a_person_with_no_bd_role_gets_the_servers_sentence_and_no_request(tmp_path):
    refused = {"status": 403, "body": {"ok": False, "error": "forbidden", "message": "Ask <b>Frankie</b> to add you."}}
    out = run(tmp_path, refused)
    assert out["fetches"] == []
    assert text(out, "ct-note") == "Ask <b>Frankie</b> to add you."
    assert "<b>" not in markup(out, "ct-note"), "the server's sentence goes in as text"
    assert shown(out, "ct-note") and not shown(out, "ct-tools")


# ── the BD tab ────────────────────────────────────────────────────────────────────────────────────
def inner(html, cls):
    """The words inside the first element whose class list starts with `cls` (its tags walked by depth,
    so nested spans stay inside it), or None."""
    m = re.search(r'<(\w+) class="%s[" ]' % re.escape(cls), html)
    if not m:
        return None
    tag, depth, i = m.group(1), 0, m.start()
    for t in re.finditer(r"<(/?)%s\b[^>]*>" % tag, html[i:]):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            body = html[i:i + t.end()]
            return " ".join(htmlmod.unescape(re.sub(r"<[^>]+>", " ", body)).split())
    return None


def rows(out):
    """([(account id, tab)], [(name, people, owner and +N, last live talk)]) for each company row, in order."""
    html = markup(out, "ct-list")
    found = re.findall(r'<div class="ct-acct[^"]*" data-acct="(\d+)" data-tab="(\w+)">', html)
    words = []
    for part in re.split(r'<div class="ct-acct[^"]*" data-acct="\d+" data-tab="\w+">', html)[1:]:
        head = part.split('class="ct-people"')[0]
        words.append((inner(head, "ct-acct-name"), inner(head, "ct-c-people"), inner(head, "ct-owner"),
                      inner(head, "ct-c-last")))
    return [(int(a), t) for a, t in found], words


def test_the_bd_tab_lists_each_account_with_its_people_owner_and_last_live_talk(tmp_path):
    out = run(tmp_path, me("salesperson"))
    ids, words = rows(out)
    assert ids == [(10, "bd"), (16, "bd")], "the server's order (by name)"
    assert words == [
        ("Prairie Ridge <b>Builders</b> LLC", "1 person", "Avery Quill", "Tue, Oct 20"),
        ("Bluestem Logistics", "3 people", "Avery Quill +1", "Never"),
    ]
    assert "<b>Builders</b>" not in markup(out, "ct-list"), "a company name goes in as text"
    assert text(out, "ct-sub") == "4 people at 2 BD accounts · 2 maintenance contacts"
    assert text(out, "ct-tab-bd") == "BD accounts 2" and text(out, "ct-tab-maintenance") == "Maintenance 1"
    assert out["els"]["ct-tab-bd"]["attrs"].get("aria-selected") == "true"
    toggles = re.findall(r'class="ct-acct-toggle"[^>]*aria-expanded="(\w+)"', markup(out, "ct-list"))
    assert toggles == ["false", "false"], "both rows start shut"


def test_an_unowned_account_says_so(tmp_path):
    wes = {"id": 18, "name": "Osage Plains Brewing", "city": "", "industry": "", "category": "bd", "people_count": 1,
           "owner": None, "other_owners": 0, "last_live_at": None, "people": [person(32, "Wes Calder", None)]}
    out = run(tmp_path, me("manager"), bd=[wes])
    assert rows(out)[1] == [("Osage Plains Brewing", "1 person", "No owner", "Never")]


def test_no_account_is_open_until_asked(tmp_path):
    out = run(tmp_path, me("admin"))
    assert "/bd/contact.html?id=" not in markup(out, "ct-list"), "the people show when an account opens"


# ── ?company= opens that account ──────────────────────────────────────────────────────────────────
def test_a_company_link_opens_that_account_with_its_people(tmp_path):
    out = run(tmp_path, me("salesperson"), search="?company=16")
    html = markup(out, "ct-list")
    assert '<div class="ct-acct is-open" data-acct="16" data-tab="bd">' in html
    assert '<div class="ct-acct" data-acct="10" data-tab="bd">' in html, "the others stay shut"
    links = re.findall(r'href="(/bd/contact\.html\?id=\d+)"', html)
    assert links == ["/bd/contact.html?id=29", "/bd/contact.html?id=27", "/bd/contact.html?id=28"]
    people = re.findall(r'class="who-name ct-p-name"[^>]*>([^<]+)<', html)
    assert people == ["Ines Varga", "Lena Ortiz", "Sam Achebe"]
    # name, title, phone, email, status (Q19): Ines needs confirming, Lena is a key account
    assert "Purchasing" in html and 'href="tel:+19135550109"' in html and "913-555-0109" in html
    assert 'href="mailto:ines.varga@bluestem.example.com"' in html
    assert "Needs confirming" in html and "Key account" in html
    assert 'href="/bd/add.html?company=16"' in html, "Add someone here, for whoever may add"


def test_a_company_link_to_a_maintenance_account_opens_the_maintenance_tab(tmp_path):
    out = run(tmp_path, me("assistant"), search="?company=17")
    assert out["els"]["ct-tab-maintenance"]["attrs"].get("aria-selected") == "true"
    html = markup(out, "ct-list")
    assert '<div class="ct-acct is-open" data-acct="17" data-tab="maintenance">' in html
    assert re.findall(r'href="(/bd/contact\.html\?id=\d+)"', html) == ["/bd/contact.html?id=30",
                                                                        "/bd/contact.html?id=31"]
    assert "Due now" in html, "Nora has never been followed up: her follow-up is due"
    assert 'data-more' not in html, "the assistant gets no move menu (Q5)"


def test_a_company_on_both_tabs_opens_on_the_tab_the_link_names(tmp_path):
    """Bluestem Logistics is on both tabs: its BD people on BD accounts, Opal Reyes (made maintenance on
    her own) on Maintenance. Opal's company link names the Maintenance tab, so it opens there with
    Opal drawn; without a tab the link opens the BD tab, the first that holds it."""
    opal = person(33, "Opal Reyes", AVERY, category="maintenance", maintenance_due_date="2027-01-15")
    bluestem_m = dict(BLUESTEM, category="maintenance", people_count=1, other_owners=0, people=[opal])
    out = run(tmp_path, me("salesperson"), search="?company=16&tab=maintenance", maint=[KAW, bluestem_m])
    assert out["els"]["ct-tab-maintenance"]["attrs"].get("aria-selected") == "true"
    assert out["els"]["ct-tab-bd"]["attrs"].get("aria-selected") == "false"
    html = markup(out, "ct-list")
    assert '<div class="ct-acct is-open" data-acct="16" data-tab="maintenance">' in html
    assert re.findall(r'href="(/bd/contact\.html\?id=\d+)"', html) == ["/bd/contact.html?id=33"]
    out = run(tmp_path, me("salesperson"), search="?company=16", maint=[KAW, bluestem_m], name="no-tab")
    assert out["els"]["ct-tab-bd"]["attrs"].get("aria-selected") == "true"
    assert '<div class="ct-acct is-open" data-acct="16" data-tab="bd">' in markup(out, "ct-list")


def test_a_company_link_naming_the_wrong_tab_opens_the_tab_that_holds_it(tmp_path):
    """Kaw Valley Cold Storage is on Maintenance only; ?tab= never strands a link on an empty tab."""
    out = run(tmp_path, me("salesperson"), search="?company=17&tab=bd")
    assert out["els"]["ct-tab-maintenance"]["attrs"].get("aria-selected") == "true"
    assert '<div class="ct-acct is-open" data-acct="17" data-tab="maintenance">' in markup(out, "ct-list")


def test_the_manager_gets_no_add_someone_here(tmp_path):
    out = run(tmp_path, me("manager"), search="?company=16")
    assert "/bd/add.html" not in markup(out, "ct-list")


# ── search (?q=) ──────────────────────────────────────────────────────────────────────────────────
SAM = {"total": 1, "items": [{"tab": "bd", "account": {"id": 16, "name": "Bluestem Logistics"},
                               "account_match": False, "people": [{"id": 28, "name": "Sam Achebe"}]}]}
NORA = {"total": 1, "items": [{"tab": "maintenance", "account": {"id": 17, "name": "Kaw Valley Cold Storage"},
                                "account_match": False, "people": [{"id": 31, "name": "Nora Lindqvist"}]}]}
BOTH = {"total": 2, "items": [
    {"tab": "bd", "account": {"id": 16, "name": "Bluestem Logistics"}, "account_match": True, "people": []},
    {"tab": "maintenance", "account": {"id": 17, "name": "Kaw Valley Cold Storage"}, "account_match": False,
     "people": [{"id": 30, "name": "Hal Brecken"}]}]}


def matched(out):
    return [int(x) for x in re.findall(r'<div class="ct-person is-match" data-contact="(\d+)"', markup(out, "ct-list"))]


def test_a_search_opens_the_account_and_highlights_the_person(tmp_path):
    out = run(tmp_path, me("salesperson"), search="?q=%28913%29%20555-0108", search_answer=SAM)
    assert "GET /api/bd/contacts/search?q=(913)%20555-0108" in asked(out), "the term rides ?q=, never the path"
    assert rows(out)[0] == [(16, "bd")], "only the matched account shows"
    assert '<div class="ct-acct is-open" data-acct="16" data-tab="bd">' in markup(out, "ct-list")
    assert matched(out) == [28]
    assert text(out, "ct-count").startswith("Sam Achebe at Bluestem Logistics.")


def test_a_maintenance_hit_opens_the_maintenance_tab(tmp_path):
    out = run(tmp_path, me("manager"), search="?q=nora", search_answer=NORA)
    assert rows(out)[0] == [(17, "maintenance")]
    assert matched(out) == [31]
    assert out["els"]["ct-tab-maintenance"]["attrs"].get("aria-selected") == "true"
    assert out["els"]["ct-tab-bd"]["attrs"].get("aria-selected") == "false"
    assert text(out, "ct-count").startswith("Nora Lindqvist at Kaw Valley Cold Storage.")


def test_hits_on_both_tabs_show_this_tabs_and_say_where_the_rest_are(tmp_path):
    out = run(tmp_path, me("admin"), search="?q=bluestem", search_answer=BOTH)
    assert rows(out)[0] == [(16, "bd")], "the BD tab first; an account-name hit opens with nobody highlighted"
    assert matched(out) == []
    assert text(out, "ct-count") == "1 account matches. 1 more on the Maintenance tab. Clear search"


def test_no_hit_says_so(tmp_path):
    out = run(tmp_path, me("admin"), search="?q=zzz", search_answer={"total": 0, "items": []})
    assert rows(out)[0] == []
    assert 'No account or person matches “zzz”.' in text(out, "ct-list")


def test_the_search_term_goes_in_as_text(tmp_path):
    out = run(tmp_path, me("admin"), search="?q=%3Cimg%20src%3Dx%3E", search_answer={"total": 0, "items": []})
    assert "<img" not in markup(out, "ct-list")
    assert "&lt;img src=x&gt;" in markup(out, "ct-list")


# ── To tidy this Friday (the assistant and the admins) ───────────────────────────────────────────
def test_to_tidy_counts_what_needs_doing(tmp_path):
    out = run(tmp_path, me("assistant"))
    # Ines needs confirming; nobody on the BD tab is a possible duplicate; one unknown call
    cards = text(out, "ct-tidy-cards")
    assert "0 Duplicates" in cards and "1 To confirm" in cards and "1 Unknown call" in cards
    assert shown(out, "ct-unknown") is False, "the calls open from their card"


# ── likely duplicate BD accounts (#811: merge_companies, the assistant and the admins) ────────────
# The fixture seed's two likely pairs, as GET /api/bd/contacts/accounts/duplicates answers them
# (docs/bd/api-contract.md), with Prairie's names made to need escaping and a phone hint added.
COTTON_A = {"id": 12, "name": "Cottonwood & Sons Paving", "city": "Olathe", "industry": "Paving", "category": "bd",
            "people_count": 1, "owner": AVERY, "other_owners": 0, "last_live_at": None,
            "people": [person(23, "Marisa Cole", AVERY, title="Owner")]}
COTTON_B = {"id": 13, "name": "Cottonwood Sons Paving Co.", "city": "Olathe", "industry": "Paving", "category": "bd",
            "people_count": 1, "owner": BLAIR, "other_owners": 0, "last_live_at": None,
            "people": [person(24, "Theo Banks", BLAIR, title="Operations")]}
PRAIRIE_INC = {"id": 11, "name": "Prairie Ridge Builders, Inc.", "city": "Overland Park", "industry": "General contractor",
               "category": "bd", "people_count": 2, "owner": BLAIR, "other_owners": 0, "last_live_at": None,
               "people": [person(33, "D. Whitlow", BLAIR, duplicate_of={"contact_id": 21, "name": "Dana Whitlow"}),
                          person(22, "Rory Sandell", BLAIR, title="Estimator")]}
EVERY_BD = [BLUESTEM, COTTON_A, COTTON_B, PRAIRIE, PRAIRIE_INC]

PAIR_COTTON = {"a": {"id": 12, "name": "Cottonwood & Sons Paving", "city": "Olathe", "people_count": 1},
               "b": {"id": 13, "name": "Cottonwood Sons Paving Co.", "city": "Olathe", "people_count": 1},
               "hints": {"phones": [], "email_domains": ["cottonwoodpaving.example.com"]}}
PAIR_PRAIRIE = {"a": {"id": 10, "name": "Prairie Ridge <b>Builders</b> LLC", "city": "Overland Park", "people_count": 1},
                "b": {"id": 11, "name": "Prairie Ridge Builders, Inc.", "city": "Overland Park", "people_count": 2},
                "hints": {"phones": ["+19135550101"], "email_domains": ["prairieridge.example.com"]}}
MERGE_41 = {"id": 41, "account": {"id": 13, "name": "Cottonwood Sons Paving Co."},
            "into": {"id": 12, "name": "Cottonwood & Sons Paving"}, "name_before": "Cottonwood & Sons Paving",
            "people": 1, "at": "2026-11-04T10:30:00-06:00", "by": {"id": 3, "name": "Casey Moret"}}
# A merge that kept the merged-away account's name, so the survivor was renamed.
MERGE_40 = {"id": 40, "account": {"id": 19, "name": "Kaw-Point Electric LLC"},
            "into": {"id": 20, "name": "Kaw-Point Electric LLC"}, "name_before": "Kaw Point Electric",
            "people": 2, "at": "2026-11-03T15:00:00-06:00", "by": {"id": 5, "name": "Emery Stoll"}}


def pairs_answer(items, merges=()):
    return ok({"total": len(items), "items": list(items), "merges": list(merges)})


def words_of(fragment):
    return " ".join(htmlmod.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def notes(out):
    """The words of each "Same account?" note, in order."""
    return [words_of(m) for m in re.findall(r'<p class="ct-pair-text">(.*?)</p>', markup(out, "ct-dupes"), re.S)]


def buttons(out, act):
    """The visible words of each data-act=`act` button in the duplicates view (screen-reader-only words cut)."""
    html = re.sub(r'<span class="sr-only">.*?</span>', "", markup(out, "ct-dupes"))
    return [words_of(m) for m in re.findall(r'<button[^>]*data-act="%s"[^>]*>(.*?)</button>' % act, html, re.S)]


def test_the_duplicates_filter_shows_each_likely_pair_as_a_same_account_note(tmp_path):
    """The mock-up's note: both names, each one's people, and the hint, worked by hand. Merge offers the
    account with more people (Prairie Ridge Builders, Inc., 2 people), the first on a tie (Cottonwood)."""
    out = run(tmp_path, me("assistant"), search="?filter=dupes", bd=EVERY_BD,
              dupes=pairs_answer([PAIR_COTTON, PAIR_PRAIRIE]))
    assert shown(out, "ct-dupes")
    assert notes(out) == [
        "Same account? “Cottonwood & Sons Paving” (1 person) and “Cottonwood Sons Paving Co.” (1 person). "
        "Both use the email domain cottonwoodpaving.example.com.",
        "Same account? “Prairie Ridge <b>Builders</b> LLC” (1 person) and “Prairie Ridge Builders, Inc.” (2 people). "
        "Both have the phone 913-555-0101 and use the email domain prairieridge.example.com.",
    ]
    assert buttons(out, "merge") == ["Merge into Cottonwood & Sons Paving", "Merge into Prairie Ridge Builders, Inc."]
    assert buttons(out, "keep") == ["Keep separate", "Keep separate"]
    assert "<b>Builders</b>" not in markup(out, "ct-dupes"), "a company name goes in as text"
    assert '<button type="button" class="chip-filter" data-chip="dupes" aria-pressed="true">' in markup(out, "ct-chips")


def test_a_pair_with_no_hint_says_so(tmp_path):
    bare = dict(PAIR_COTTON, hints={"phones": [], "email_domains": []})
    out = run(tmp_path, me("admin"), search="?filter=dupes", bd=EVERY_BD, dupes=pairs_answer([bare]))
    assert notes(out) == ["Same account? “Cottonwood & Sons Paving” (1 person) and “Cottonwood Sons Paving Co.” "
                          "(1 person). No shared phone or email domain."]


def test_the_duplicates_filter_lists_the_flagged_people_and_both_accounts_of_each_pair(tmp_path):
    """D. Whitlow (Prairie Ridge Builders, Inc.) is a flagged person; Cottonwood and Prairie are the two
    pairs. Bluestem is neither, so it is the one account left out."""
    out = run(tmp_path, me("super_admin"), search="?filter=dupes", bd=EVERY_BD,
              dupes=pairs_answer([PAIR_COTTON, PAIR_PRAIRIE]))
    assert rows(out)[0] == [(12, "bd"), (13, "bd"), (10, "bd"), (11, "bd")]


def test_to_tidy_counts_the_pairs_with_the_flagged_people(tmp_path):
    """1 flagged person (D. Whitlow) + 2 likely pairs = 3, as the mock-up counts its Duplicates card."""
    out = run(tmp_path, me("assistant"), bd=EVERY_BD, dupes=pairs_answer([PAIR_COTTON, PAIR_PRAIRIE]))
    assert "3 Duplicates" in text(out, "ct-tidy-cards")
    assert not shown(out, "ct-dupes"), "the notes are on the Possible duplicates filter only"


@pytest.mark.parametrize("role", ["salesperson", "manager"])
def test_a_salesperson_and_the_manager_never_see_the_pairs(tmp_path, role):
    """Q21, Q36: not even from a link that names the filter, and the route is never asked."""
    out = run(tmp_path, me(role), search="?filter=dupes", bd=EVERY_BD, dupes=pairs_answer([PAIR_COTTON], [MERGE_41]),
              name=role)
    assert not any(a.startswith("GET /api/bd/contacts/accounts/duplicates") for a in asked(out))
    assert not shown(out, "ct-dupes")
    assert all("Same account?" not in e["html"] and "Recently merged" not in e["html"] for e in out["els"].values())
    assert len(rows(out)[0]) == 5, "no filter they may not use: every BD account shows"


def test_the_notes_follow_merge_companies_not_the_chip(tmp_path):
    """The Possible duplicates chip is clear_duplicate's (#810); the pairs are merge_companies' (#811).
    Today both go to the same roles, so this can is made up: the chip, its flagged people, and no pair."""
    who = me("assistant")
    who["body"]["can"] = dict(who["body"]["can"], merge_companies=False)
    out = run(tmp_path, who, search="?filter=dupes", bd=EVERY_BD, dupes=pairs_answer([PAIR_COTTON], [MERGE_41]))
    assert not any("duplicates" in a for a in asked(out))
    assert '<button type="button" class="chip-filter" data-chip="dupes" aria-pressed="true">' in markup(out, "ct-chips")
    assert not shown(out, "ct-dupes")
    assert rows(out)[0] == [(11, "bd")], "only the flagged person's account"
    assert "1 Duplicate" in text(out, "ct-tidy-cards")


def test_recently_merged_lists_each_merge_with_its_undo(tmp_path):
    """The merges the route lists, newest first, each with an Undo naming it; the survivor of each shows
    in the list (Cottonwood & Sons Paving, with the person moved in), the merged-away one does not."""
    out = run(tmp_path, me("assistant"), search="?filter=dupes", bd=[BLUESTEM, COTTON_A, PRAIRIE, PRAIRIE_INC],
              dupes=pairs_answer([PAIR_PRAIRIE], [MERGE_41, MERGE_40]))
    html = markup(out, "ct-dupes")
    assert "Recently merged" in text(out, "ct-dupes")
    merged = [words_of(m) for m in re.findall(r'<li class="ct-merged-row">(.*?)</li>', html, re.S)]
    assert merged == [
        "Cottonwood Sons Paving Co. into Cottonwood & Sons Paving 1 person moved · Wed, Nov 4 by Casey Moret "
        "Undo merging Cottonwood Sons Paving Co. into Cottonwood & Sons Paving",
        "Kaw-Point Electric LLC into Kaw Point Electric, now named Kaw-Point Electric LLC 2 people moved · Tue, Nov 3 "
        "by Emery Stoll Undo merging Kaw-Point Electric LLC into Kaw Point Electric",
    ]
    assert re.findall(r'data-act="unmerge" data-id="(\d+)"', html) == ["41", "40"]
    assert rows(out)[0] == [(12, "bd"), (10, "bd"), (11, "bd")]


def test_no_pair_and_no_merge_says_so(tmp_path):
    out = run(tmp_path, me("admin"), search="?filter=dupes", bd=EVERY_BD, dupes=pairs_answer([]))
    assert text(out, "ct-dupes") == "No two accounts look like the same company."
    assert "Recently merged" not in text(out, "ct-dupes")


def test_the_pairs_not_loading_says_why_and_the_list_still_shows(tmp_path):
    behind = {"status": 503, "body": {"ok": False, "error": "db_behind", "message": "The <i>BD</i> database is not up to date."}}
    out = run(tmp_path, me("assistant"), search="?filter=dupes", bd=EVERY_BD, dupes=behind)
    assert text(out, "ct-dupes") == "The <i>BD</i> database is not up to date."
    assert "<i>" not in markup(out, "ct-dupes")
    assert rows(out)[0] == [(11, "bd")], "the flagged person's account still shows"
    assert "0 Duplicates" not in text(out, "ct-tidy-cards") and "1 Duplicate" in text(out, "ct-tidy-cards")


def test_the_pairs_are_read_page_by_page_until_the_total(tmp_path):
    """The duplicates route pages at 500 too: the page asks again from where the last answer stopped."""
    require_node()
    res = responses()
    res.pop("GET /api/bd/contacts/accounts")
    sc = {"scripts": ["js/crm-core.js"] + page_scripts(), "token": "tok", "ready": True, "bdMe": me("admin"),
          "now": MORNING, "ids": IDS, "responses": res, "search": "?filter=dupes", "pathname": "/bd/contacts.html",
          "byQuery": {
              "GET /api/bd/contacts/accounts": {
                  "category=bd": ok({"category": "bd", "total": len(EVERY_BD), "items": EVERY_BD}),
                  "category=maintenance": ok({"category": "maintenance", "total": 0, "items": []})},
              "GET /api/bd/contacts/accounts/duplicates": {
                  "offset=0": ok({"total": 2, "items": [PAIR_COTTON], "merges": [MERGE_41]}),
                  "offset=1": ok({"total": 2, "items": [PAIR_PRAIRIE], "merges": [MERGE_41]})}}}
    f = tmp_path / "pairs-paging.json"
    f.write_text(json.dumps(sc), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f)
    out = last_json_line(proc.stdout)
    assert out["threw"] is None, out["threw"]
    assert [a for a in asked(out) if "duplicates" in a] == [
        "GET /api/bd/contacts/accounts/duplicates?limit=500&offset=0",
        "GET /api/bd/contacts/accounts/duplicates?limit=500&offset=1"]
    assert len(notes(out)) == 2
    assert re.findall(r'data-act="unmerge" data-id="(\d+)"', markup(out, "ct-dupes")) == ["41"], "one list of merges"


# ── the move menu's words ─────────────────────────────────────────────────────────────────────────
def test_every_company_row_names_its_menu(tmp_path):
    out = run(tmp_path, me("salesperson"))
    labels = re.findall(r'data-more[^>]*aria-label="([^"]+)"', markup(out, "ct-list"))
    assert [htmlmod.unescape(x) for x in labels] == ["More for Prairie Ridge <b>Builders</b> LLC",
                                                     "More for Bluestem Logistics"]


# ── paging ────────────────────────────────────────────────────────────────────────────────────────
def test_a_tab_is_read_page_by_page_until_the_total(tmp_path):
    """The account list pages at 500: the page asks again from where the last answer stopped."""
    require_node()
    res = responses()
    res.pop("GET /api/bd/contacts/accounts")
    page1 = ok({"category": "bd", "total": 2, "items": [PRAIRIE]})
    page2 = ok({"category": "bd", "total": 2, "items": [BLUESTEM]})
    sc = {"scripts": ["js/crm-core.js"] + page_scripts(), "token": "tok", "ready": True, "bdMe": me("manager"),
          "now": MORNING, "ids": IDS, "responses": res, "search": "", "pathname": "/bd/contacts.html",
          "byQuery": {"GET /api/bd/contacts/accounts": {
              "offset=1": page2,
              "category=bd": page1,
              "category=maintenance": ok({"category": "maintenance", "total": 0, "items": []})}}}
    f = tmp_path / "paging.json"
    f.write_text(json.dumps(sc), encoding="utf-8")
    proc = run_node(HARNESS, FRONTEND, f)
    out = last_json_line(proc.stdout)
    assert out["threw"] is None, out["threw"]
    assert asked(out) == ["GET /api/bd/contacts/accounts?category=bd&limit=500&offset=0",
                          "GET /api/bd/contacts/accounts?category=bd&limit=500&offset=1",
                          "GET /api/bd/contacts/accounts?category=maintenance&limit=500&offset=0"]
    assert rows(out)[0] == [(10, "bd"), (16, "bd")]
