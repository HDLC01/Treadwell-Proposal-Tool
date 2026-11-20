"""The Contacts page's search (#810, Q22, Q35): GET /api/bd/contacts/search?q= (bd/routers/accounts.py).

It matches account names, people's names, phones in any format (on the last 10 digits) and emails in
any case. Each item is one account on one tab, with the people who matched there, so the page opens
that account on that tab and highlights them: a BD person's hit is on the BD tab, a maintenance
person's on the Maintenance tab. The term travels as ?q= only, and no part of it reaches the audit
log or BD's event history.

The fixture seed (bd/ops/fixture_seed.py, today Wed 2026-11-04), as worked out by hand:
    16 Bluestem Logistics          Lena Ortiz 27, Sam Achebe 28 (913-555-0108), Ines Varga 29
    12 Cottonwood & Sons Paving    Marisa Cole 23      13 Cottonwood Sons Paving Co.   Theo Banks 24
    10 Prairie Ridge Builders LLC  Dana Whitlow 21     11 Prairie Ridge Builders, Inc. D. Whitlow 33
                                                          (Dana.Whitlow@prairieridge.example.com), Rory 22
    17 Kaw Valley Cold Storage     Hal Brecken 30 (hal@kawvalley.example.com), Nora Lindqvist 31:
                                   maintenance people
Everything is made up: example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import urllib.parse

import pytest

AVERY, BLAIR, CASEY, DEVON = 1, 2, 3, 4
URL = "/api/bd/contacts/search"


def search(client, term):
    r = client.get(URL + "?q=" + urllib.parse.quote(term, safe=""))
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"ok", "total", "items"} and body["ok"] is True and body["total"] == len(body["items"])
    return body["items"]


def hits(items):
    """[(tab, account id, account matched, [people ids])]"""
    return [(i["tab"], i["account"]["id"], i["account_match"], [p["id"] for p in i["people"]]) for i in items]


def test_an_account_name(bd_seeded, bd_as_user):
    items = search(bd_as_user(AVERY), "logistics")
    assert items == [{"tab": "bd", "account": {"id": 16, "name": "Bluestem Logistics"}, "account_match": True,
                      "people": []}]
    # "bluestem" is in the account's name AND in each of its people's emails (@bluestem.example.com).
    assert hits(search(bd_as_user(AVERY), "bluestem")) == [("bd", 16, True, [29, 27, 28])]


@pytest.mark.parametrize("term,want", [
    ("BLUESTEM log", [("bd", 16, True, [])]),
    ("cottonwood sons", [("bd", 12, True, []), ("bd", 13, True, [])]),   # 12 by its cleaned name
    ("cottonwood & sons", [("bd", 12, True, []), ("bd", 13, True, [])]),  # 13 by the cleaned term
    ("kaw valley", [("maintenance", 17, True, [])]),                     # a maintenance account
    ("zzz", []),
    ("%", []),                                                            # text, never a pattern
    ("inc", [("bd", 11, True, [])]),                                      # cleans to nothing: names only
])
def test_account_names(bd_seeded, bd_as_user, term, want):
    assert hits(search(bd_as_user(CASEY), term)) == want


def test_a_person_by_name_returns_their_account_and_them(bd_seeded, bd_as_user):
    items = search(bd_as_user(BLAIR), "ortiz")
    assert items == [{"tab": "bd", "account": {"id": 16, "name": "Bluestem Logistics"}, "account_match": False,
                      "people": [{"id": 27, "name": "Lena Ortiz"}]}]
    assert hits(search(bd_as_user(BLAIR), "LeNa oRtIz")) == [("bd", 16, False, [27])]


def test_one_name_at_two_accounts(bd_seeded, bd_as_user):
    assert hits(search(bd_as_user(DEVON), "whitlow")) == [("bd", 10, False, [21]), ("bd", 11, False, [33])]


@pytest.mark.parametrize("term", ["913-555-0108", "(913) 555-0108", "913.555.0108", "+1 913 555 0108",
                                  "9135550108", "1-913-555-0108", "19135550108"])
def test_a_phone_in_any_format(bd_seeded, bd_as_user, term):
    assert hits(search(bd_as_user(AVERY), term)) == [("bd", 16, False, [28])]


def test_a_phone_is_matched_on_its_last_ten_digits_only(bd_seeded, bd_as_user):
    assert search(bd_as_user(AVERY), "555-0108") == []
    assert search(bd_as_user(AVERY), "913-555-0199") == []
    # Ten digits that sit inside Sam's +19135550108 but are not its last ten: no match.
    assert search(bd_as_user(AVERY), "1-913-555-010") == []


@pytest.mark.parametrize("term", ["Rory.Sandell@PrairieRidgeBuilders.Example.com",
                                  "RORY.SANDELL@prairieridgebuilders.example.com", "rory.sandell@"])
def test_an_email_in_any_case(bd_seeded, bd_as_user, term):
    assert hits(search(bd_as_user(CASEY), term)) == [("bd", 11, False, [22])]


def test_an_email_stored_in_capitals_is_found_by_a_lower_case_term(bd_seeded, bd_as_user):
    """D. Whitlow's email is stored as Dana.Whitlow@prairieridge.example.com."""
    assert hits(search(bd_as_user(CASEY), "dana.whitlow@prairieridge")) == [("bd", 10, False, [21]),
                                                                              ("bd", 11, False, [33])]


def test_a_maintenance_person_is_found_for_the_maintenance_tab(bd_seeded, bd_as_user):
    items = search(bd_as_user(AVERY), "Hal@KawValley.Example.COM")
    assert items == [{"tab": "maintenance", "account": {"id": 17, "name": "Kaw Valley Cold Storage"},
                      "account_match": False, "people": [{"id": 30, "name": "Hal Brecken"}]}]
    assert hits(search(bd_as_user(AVERY), "nora")) == [("maintenance", 17, False, [31])]
    assert hits(search(bd_as_user(AVERY), "785-555-0111")) == [("maintenance", 17, False, [31])]


def test_an_account_on_both_tabs_is_found_on_each(bd_seeded, bd_as_user, bd_db):
    """A maintenance person at Bluestem: the account is on both tabs, so a name hit lists both, and a
    person's hit says which tab they are on."""
    mx = bd_db.execute("insert into bd.contacts (company_id, name, category, owner_id, frequency_per_year)"
                       " values (16, 'Tobin Reyes', 'maintenance', 1, 3) returning id").fetchone()["id"]
    assert hits(search(bd_as_user(AVERY), "logistics")) == [("bd", 16, True, []), ("maintenance", 16, True, [])]
    assert hits(search(bd_as_user(AVERY), "tobin")) == [("maintenance", 16, False, [mx])]
    assert hits(search(bd_as_user(AVERY), "bluestem.example.com")) == [("bd", 16, False, [29, 27, 28])]


def test_an_archived_person_is_not_found(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("update bd.contacts set archived_at = bd_now() where id = 27")
    assert search(bd_as_user(AVERY), "ortiz") == []


@pytest.mark.parametrize("query,field", [
    ("", "Type something to search for."),
    ("?q=", "Type something to search for."),
    ("?q=%20%20", "Type something to search for."),
    ("?q=" + "a" * 201, "Keep this to 200 characters or fewer."),
])
def test_a_blank_or_long_term_is_400(bd_seeded, bd_as_user, query, field):
    r = bd_as_user(AVERY).get(URL + query)
    assert (r.status_code, r.json()) == (400, {"ok": False, "error": "bad_request",
                                               "message": "Some fields need fixing.", "fields": {"q": field}})


def test_two_hundred_characters_is_fine(bd_seeded, bd_as_user):
    assert search(bd_as_user(AVERY), "a" * 200) == []


# ── the term is never written down ──────────────────────────────────────────────────────────────
TERMS = ("Sam Achebe 913-555-0108", "achebe", "(913) 555-0108", "sam.achebe@bluestem.example.com")
# The parts of those terms no audit field could hold by chance (the signed-in email is
# blair.fenn@example.com, so "example.com" alone proves nothing).
DISTINCT = ("sam", "achebe", "ache", "chebe", "913", "0108", "555-0108", "5550108", "9135550108", "sam.achebe",
            "bluestem")


def test_no_part_of_the_term_reaches_the_audit_log_or_the_event_history(bd_seeded, bd_as_user, bd_db,
                                                                         monkeypatch):
    import main

    written = []
    monkeypatch.setattr(main.audit, "audit_log", lambda record: written.append(dict(record)))
    events_before = bd_db.execute("select count(*) as n, coalesce(max(id), 0) as last from bd.events").fetchone()
    client = bd_as_user(BLAIR)
    assert client.get(URL + "?q=zzqx").status_code == 200          # the control: a term nobody matches
    for term in TERMS:
        assert client.get(URL + "?q=" + urllib.parse.quote(term)).status_code == 200
    # Every search is audited (its path holds /contacts: a read of people), and each record is the
    # control's record exactly, but for its time: method, path (no query), who, status, address.
    assert len(written) == 1 + len(TERMS), written
    plain = [{k: v for k, v in r.items() if k != "ts"} for r in written]
    assert plain[0]["path"] == URL and plain[0]["method"] == "GET" and plain[0]["status"] == 200
    assert all(r == plain[0] for r in plain[1:]), plain
    text = repr(plain).lower()
    assert [p for p in DISTINCT if p in text] == []
    # BD's event history: a search writes nothing at all.
    after = bd_db.execute("select count(*) as n, coalesce(max(id), 0) as last from bd.events").fetchone()
    assert after == events_before
    blob = repr(bd_db.execute("select kind, detail, data::text as data from bd.events").fetchall()).lower()
    assert [p for p in DISTINCT if p in blob] == []
