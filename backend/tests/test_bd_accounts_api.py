"""The Contacts page's account list (#810): GET /api/bd/contacts/accounts, the BD tab and the
Maintenance tab (bd/routers/accounts.py).

On the fixture seed (bd/ops/fixture_seed.py, today Wed 2026-11-04), worked out here by hand. The BD
people at each account (archived people never count):
    16 Bluestem Logistics             Ines 29 (Devon's), Lena 27 (Avery's), Sam 28 (Blair's): Avery and
                                      Blair tie 1-1 (Devon is the manager, and only salespeople own an
                                      account, Q33)
    14 Cedar Creek Concrete           Priya 25 (Avery's)           a no-answer call Nov 3: not live
    15 Cedar Crest Concrete           Owen 26 (Blair's)            a text Nov 1: not live
    12 Cottonwood & Sons Paving       Marisa 23 (Avery's)          a meeting Jun 15 14:00 UTC
    13 Cottonwood Sons Paving Co.     Theo 24 (Blair's)
    18 Osage Plains Brewing           Wes 32 (nobody's)
    10 Prairie Ridge Builders LLC     Dana 21 (Avery's)            an answered call Oct 20 15:00 UTC
    11 Prairie Ridge Builders, Inc.   D. Whitlow 33, Rory 22 (both Blair's)
    17 Kaw Valley Cold Storage        Hal 30, Nora 31: maintenance people only, so NOT on the BD tab;
                                      Hal's answered call Aug 20 15:00 UTC is its last live talk
Central time is CDT (-05:00) until Sun Nov 1 2026, CST (-06:00) after. Everything is made up:
example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import pytest

AVERY, BLAIR, CASEY, DEVON, EMERY, FRANKIE = 1, 2, 3, 4, 5, 6
URL = "/api/bd/contacts/accounts"
BD_ORDER = [16, 14, 15, 12, 13, 18, 10, 11]          # the name in lower case, byte by byte
ACCOUNT_KEYS = {"id", "name", "city", "industry", "category", "people_count", "owner", "other_owners",
                "last_live_at", "people"}
PERSON_KEYS = {"id", "name", "title", "phone", "phone_e164", "email", "category", "confirmed", "importance",
               "owner", "duplicate_of", "lead_source", "last_live_at", "last_followup_at", "cadence_status",
               "cadence", "cadence_source", "cadence_override_until", "maintenance_due", "maintenance_due_date"}
AVERY_REF = {"id": AVERY, "name": "Avery Quill"}
BLAIR_REF = {"id": BLAIR, "name": "Blair Fenn"}
GALE, GALE_REF = 7, {"id": 7, "name": "Gale Ward"}


def accounts(client, query=""):
    r = client.get(URL + query)
    assert r.status_code == 200, r.text
    return r.json()


def by_id(body):
    return {a["id"]: a for a in body["items"]}


def summary(a):
    """The row the page draws: people, owner, +N, last live talk."""
    return (a["people_count"], a["owner"], a["other_owners"], a["last_live_at"], [p["id"] for p in a["people"]])


def talk(db, contact_id, user_id, at_utc, kind="call", outcome="answered"):
    db.execute("insert into bd.interactions (contact_id, user_id, kind, outcome, occurred_at)"
               " values (%s, %s, %s, %s, %s)", (contact_id, user_id, kind, outcome, at_utc + "+00:00"))


def add_person(db, company_id, name, owner_id, category="bd"):
    return db.execute(
        "insert into bd.contacts (company_id, name, category, owner_id, frequency_per_year)"
        " values (%s, %s, %s, %s, 4) returning id", (company_id, name, category, owner_id)).fetchone()["id"]


# ── the BD tab on the seed ──────────────────────────────────────────────────────────────────────
def test_the_bd_tab_on_the_seed(bd_seeded, bd_as_user):
    body = accounts(bd_as_user(AVERY))
    assert set(body) == {"ok", "category", "total", "items"}
    assert (body["ok"], body["category"], body["total"]) == (True, "bd", 8)
    assert [a["id"] for a in body["items"]] == BD_ORDER
    got = {a["id"]: summary(a) for a in body["items"]}
    assert got == {
        16: (3, AVERY_REF, 1, None, [29, 27, 28]),        # Avery and Blair tie, nobody talked live: by name
        14: (1, AVERY_REF, 0, None, [25]),
        15: (1, BLAIR_REF, 0, None, [26]),
        12: (1, AVERY_REF, 0, "2026-06-15T09:00:00-05:00", [23]),
        13: (1, BLAIR_REF, 0, None, [24]),
        18: (1, None, 0, None, [32]),                     # an unowned person: no owner
        10: (1, AVERY_REF, 0, "2026-10-20T10:00:00-05:00", [21]),
        11: (2, BLAIR_REF, 0, None, [33, 22]),
    }
    for a in body["items"]:
        assert set(a) == ACCOUNT_KEYS and a["category"] == "bd"
        assert all(set(p) == PERSON_KEYS and p["category"] == "bd" for p in a["people"])


def test_an_account_row_and_its_people(bd_seeded, bd_as_user):
    row = by_id(accounts(bd_as_user(CASEY)))[10]
    assert {k: row[k] for k in ("id", "name", "city", "industry")} == {
        "id": 10, "name": "Prairie Ridge Builders LLC", "city": "Overland Park", "industry": "General contractor"}
    assert row["people"] == [{
        "id": 21, "name": "Dana Whitlow", "title": "Project Manager", "phone": "913-555-0101",
        "phone_e164": "+19135550101", "email": "dana.whitlow@prairieridge.example.com", "category": "bd",
        "confirmed": True, "importance": 3, "owner": AVERY_REF, "duplicate_of": None, "lead_source": "Referral",
        "last_live_at": "2026-10-20T10:00:00-05:00", "last_followup_at": "2026-11-02T10:00:00-06:00",
        "cadence_status": "on_track", "cadence": "quarterly", "cadence_source": "global",
        "cadence_override_until": None, "maintenance_due": False, "maintenance_due_date": None}]


def test_the_status_a_person_wears(bd_seeded, bd_as_user):
    """What the page's status pill reads: a possible duplicate, needs confirming, a cadence override."""
    rows = by_id(accounts(bd_as_user(DEVON)))
    whitlow = rows[11]["people"][0]
    assert (whitlow["id"], whitlow["confirmed"], whitlow["duplicate_of"]) == (33, False, {
        "contact_id": 21, "name": "Dana Whitlow", "company": "Prairie Ridge Builders LLC", "reason": "Same email"})
    lena = [p for p in rows[16]["people"] if p["id"] == 27][0]
    assert (lena["cadence"], lena["cadence_source"], lena["cadence_override_until"], lena["importance"]) == (
        "monthly", "override", "2026-12-31", 3)


# ── the Maintenance tab (Q6) ────────────────────────────────────────────────────────────────────
def test_the_maintenance_tab_lists_companies_with_their_maintenance_people(bd_seeded, bd_as_user):
    body = accounts(bd_as_user(BLAIR), "?category=maintenance")
    assert (body["category"], body["total"], [a["id"] for a in body["items"]]) == ("maintenance", 1, [17])
    kaw = body["items"][0]
    assert summary(kaw) == (2, AVERY_REF, 0, "2026-08-20T10:00:00-05:00", [30, 31])
    hal, nora = kaw["people"]
    assert (hal["name"], hal["maintenance_due"], hal["maintenance_due_date"], hal["last_followup_at"]) == (
        "Hal Brecken", False, "2026-12-18", "2026-08-20T10:00:00-05:00")       # Aug 20 + 120 days
    assert (nora["name"], nora["maintenance_due"], nora["maintenance_due_date"]) == ("Nora Lindqvist", True, None)
    assert kaw["category"] == "maintenance" and all(p["category"] == "maintenance" for p in kaw["people"])


def test_an_account_with_only_maintenance_people_is_not_on_the_bd_tab(bd_seeded, bd_as_user):
    assert 17 not in by_id(accounts(bd_as_user(AVERY)))


def test_maintenance_people_never_count_on_the_bd_tab(bd_seeded, bd_as_user, bd_db):
    """A maintenance person at Bluestem, owned by Gale (a salesperson whose login is off), with an
    answered call this morning (Q34): the BD row's last live talk moves to it, but the person, and
    Gale as an owner, do not count there."""
    mx = add_person(bd_db, 16, "Tobin Reyes", GALE, category="maintenance")
    talk(bd_db, mx, GALE, "2026-11-04 14:00:00")
    bd_row = by_id(accounts(bd_as_user(AVERY)))[16]
    assert summary(bd_row) == (3, AVERY_REF, 1, "2026-11-04T08:00:00-06:00", [29, 27, 28])
    m_rows = by_id(accounts(bd_as_user(AVERY), "?category=maintenance"))
    assert summary(m_rows[16]) == (1, GALE_REF, 0, "2026-11-04T08:00:00-06:00", [mx])


# ── the owner and "+N" (Q33, Q41) ───────────────────────────────────────────────────────────────
def test_a_tie_goes_to_the_owner_with_the_latest_live_talk_at_the_account(bd_seeded, bd_as_user, bd_db):
    talk(bd_db, 27, AVERY, "2026-10-30 15:00:00", kind="meeting", outcome=None)    # Avery meets Lena
    talk(bd_db, 28, BLAIR, "2026-11-02 15:00:00")                                    # Blair talks to Sam
    assert summary(by_id(accounts(bd_as_user(AVERY)))[16])[:4] == (3, BLAIR_REF, 1, "2026-11-02T09:00:00-06:00")
    talk(bd_db, 29, DEVON, "2026-11-03 18:00:00", kind="hosted", outcome=None)       # Devon hosts Ines
    # Devon is the manager: his talk is the latest at the account, but he is not one of its owners.
    assert summary(by_id(accounts(bd_as_user(AVERY)))[16])[:4] == (3, BLAIR_REF, 1, "2026-11-03T12:00:00-06:00")
    talk(bd_db, 27, AVERY, "2026-11-03 20:00:00")                                    # Avery talks to Lena
    assert summary(by_id(accounts(bd_as_user(AVERY)))[16])[:4] == (3, AVERY_REF, 1, "2026-11-03T14:00:00-06:00")


def test_only_a_live_talk_by_a_tied_owner_breaks_the_tie(bd_seeded, bd_as_user, bd_db):
    talk(bd_db, 28, BLAIR, "2026-11-02 15:00:00")
    talk(bd_db, 27, EMERY, "2026-11-03 20:00:00")                   # not an owner there: moves the date only
    talk(bd_db, 27, AVERY, "2026-11-04 15:00:00", kind="voicemail", outcome="voicemail")
    talk(bd_db, 27, AVERY, "2026-11-04 15:30:00", outcome="no_answer")
    talk(bd_db, 27, AVERY, "2026-11-04 16:00:00", kind="email", outcome=None)
    talk(bd_db, 27, AVERY, "2026-11-10 15:00:00")                   # dated after today: not yet
    assert summary(by_id(accounts(bd_as_user(AVERY)))[16])[:4] == (3, BLAIR_REF, 1, "2026-11-03T14:00:00-06:00")


def test_the_most_people_wins_over_the_latest_talk(bd_seeded, bd_as_user, bd_db):
    add_person(bd_db, 16, "Quinn Harlow", AVERY)
    talk(bd_db, 28, BLAIR, "2026-11-03 18:00:00")
    assert summary(by_id(accounts(bd_as_user(AVERY)))[16])[:3] == (4, AVERY_REF, 1)


def test_only_salespeople_own_an_account(bd_seeded, bd_as_user, bd_db):
    """Q33: the owner is the SALESPERSON who owns the most people there, and "+N" counts the other
    salespeople. Devon (manager) gets two more people at Bluestem, three in all: still Avery (1) and
    Blair (1) tie, Avery by name, "+1". Emery (admin) owns everyone at a new account: nobody owns it."""
    add_person(bd_db, 16, "Quinn Harlow", DEVON)
    add_person(bd_db, 16, "Rhea Moss", DEVON)
    from bd.normalize import normalize_company

    co = bd_db.execute("insert into bd.companies (name, normalized_name) values (%s, %s) returning id",
                       ("Aspen Row Glass", normalize_company("Aspen Row Glass"))).fetchone()["id"]
    add_person(bd_db, co, "Uma Fell", EMERY)
    rows = by_id(accounts(bd_as_user(AVERY)))
    assert summary(rows[16])[:3] == (5, AVERY_REF, 1)
    assert summary(rows[co])[:3] == (1, None, 0)


def test_archived_people_are_left_out_of_every_number(bd_seeded, bd_as_user, bd_db):
    talk(bd_db, 28, BLAIR, "2026-11-02 15:00:00")
    bd_db.execute("update bd.contacts set archived_at = bd_now() where id in (28, 32)")
    body = accounts(bd_as_user(AVERY))
    assert body["total"] == 7 and 18 not in by_id(body)           # Wes was Osage Plains' only person
    # Sam gone: his talk no longer counts, and Blair owns nobody there. Avery is the one salesperson.
    assert summary(by_id(body)[16]) == (2, AVERY_REF, 0, None, [29, 27])


# ── paging, sorting, bad queries ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("query,want", [
    ("?limit=3&offset=3", BD_ORDER[3:6]),
    ("?limit=0", BD_ORDER),
    ("?offset=40", []),
    ("?sort=name", BD_ORDER),
    ("?sort=people", [16, 11, 14, 15, 12, 13, 18, 10]),           # most people, then by name
    ("?sort=last_live_at", [10, 12, 16, 14, 15, 13, 18, 11]),     # latest first, never-talked by name
    ("?category=bd&sort=people&limit=2", [16, 11]),
])
def test_paging_and_sorting(bd_seeded, bd_as_user, query, want):
    body = accounts(bd_as_user(DEVON), query)
    assert (body["total"], [a["id"] for a in body["items"]]) == (8, want)


@pytest.mark.parametrize("query,message,fields", [
    ("?category=vip", "Some fields need fixing.", {"category": "Use bd or maintenance."}),
    ("?sort=owner", "Unknown sort.", {"sort": "Use name, people or last_live_at."}),
    ("?limit=-1", "Some fields need fixing.", {"limit": "Use a whole number from 0."}),
    ("?offset=x", "Some fields need fixing.", {"offset": "Use a whole number."}),
])
def test_a_bad_query_is_400(bd_seeded, bd_as_user, query, message, fields):
    r = bd_as_user(AVERY).get(URL + query)
    assert (r.status_code, r.json()) == (400, {"ok": False, "error": "bad_request", "message": message,
                                               "fields": fields})


def test_every_bd_contact_still_has_exactly_one_company(bd_seeded, bd_as_user, bd_db):
    """No reshape: the list reads the contacts as they are; each person is under one account."""
    seen = [p["id"] for tab in ("bd", "maintenance")
            for a in accounts(bd_as_user(EMERY), "?category=" + tab)["items"] for p in a["people"]]
    live = [r["id"] for r in bd_db.execute("select id from bd.contacts where archived_at is null").fetchall()]
    assert sorted(seen) == sorted(live) and len(seen) == len(set(seen))
