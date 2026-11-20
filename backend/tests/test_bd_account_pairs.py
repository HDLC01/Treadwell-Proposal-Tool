"""Likely duplicate BD accounts (#811): the matching rule and GET /api/bd/contacts/accounts/duplicates.

THE RULE (#802 "Possible duplicate BD accounts", the ticket's words). Two accounts are a likely pair
when their CLEANED names are equal. Cleaning drops company endings (LLC, Inc, Co, Corp, Ltd and the
like), drops punctuation (and "&" or "and" between words) and expands short forms such as "Const."
to "Construction". A shared phone, or a shared email domain that is not a free mail domain such as
gmail.com, is shown next to a pair as a HINT and never makes a pair alone. A merged-away account and
a kept pair are never listed.

Worked by hand on the fixture seed (bd/ops/fixture_seed.py):
    12 Cottonwood & Sons Paving      Marisa 23  816.555.0103   marisa@cottonwoodpaving.example.com
    13 Cottonwood Sons Paving Co.    Theo 24    816 555 0104   theo@cottonwoodpaving.example.com
        -> one pair: both clean to "cottonwood sons paving"; hint: the shared domain, no shared phone
    10 Prairie Ridge Builders LLC    Dana 21    913-555-0101   dana.whitlow@prairieridge.example.com
    11 Prairie Ridge Builders, Inc.  Rory 22    (913) 555-0102 rory.sandell@prairieridgebuilders.example.com
                                     D. Whitlow 33  no phone   Dana.Whitlow@prairieridge.example.com
        -> one pair; hint: prairieridge.example.com (Dana and D. Whitlow), no shared phone
    14 Cedar Creek Concrete / 15 Cedar Crest Concrete: the NEAR MISS. Priya and Owen share a phone
        (785-555-0105 and +1 785 555 0105) and the domain cedarcreek.example.com, but the names differ,
        so it is not a pair.
Pairs come cottonwood first (cleaned name order), each with the lower id as "a". Everything is
made up: example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import pytest

from bd import normalize

AVERY, BLAIR, CASEY = 1, 2, 3
URL = "/api/bd/contacts/accounts/duplicates"

SEED_PAIRS = [
    {"a": {"id": 12, "name": "Cottonwood & Sons Paving", "city": "Olathe", "people_count": 1},
     "b": {"id": 13, "name": "Cottonwood Sons Paving Co.", "city": "Olathe", "people_count": 1},
     "hints": {"phones": [], "email_domains": ["cottonwoodpaving.example.com"]}},
    {"a": {"id": 10, "name": "Prairie Ridge Builders LLC", "city": "Overland Park", "people_count": 1},
     "b": {"id": 11, "name": "Prairie Ridge Builders, Inc.", "city": "Overland Park", "people_count": 2},
     "hints": {"phones": [], "email_domains": ["prairieridge.example.com"]}},
]


# ── made-up data ────────────────────────────────────────────────────────────────────────────────
def company(db, name, city="Lenexa"):
    return db.execute("insert into bd.companies (name, normalized_name, city) values (%s, %s, %s) returning id",
                      (name, normalize.normalize_company(name), city)).fetchone()["id"]


def person(db, company_id, name, owner=AVERY, phone=None, email=None, category="bd", archived=False):
    return db.execute(
        "insert into bd.contacts (company_id, name, owner_id, phone, email, category, archived_at)"
        " values (%s, %s, %s, %s, %s, %s, case when %s then bd_now() end) returning id",
        (company_id, name, owner, phone, email, category, archived)).fetchone()["id"]


def bd_pair(db, first, second):
    """Two made-up accounts, the first with one BD person: a pair is only listed when one side is on
    the BD tab, so a rule check needs one there."""
    a, b = company(db, first), company(db, second)
    person(db, a, "Rae Lindgren")
    return a, b


def duplicates(client, query=""):
    r = client.get(URL + query)
    assert r.status_code == 200, r.text
    return r.json()


def pairs(client, query=""):
    return [(p["a"]["id"], p["b"]["id"]) for p in duplicates(client, query)["items"]]


# ── the fixture seed's two likely pairs and its near miss ───────────────────────────────────────
def test_the_seeds_two_likely_pairs_and_not_its_near_miss(bd_seeded, bd_as_user):
    body = duplicates(bd_as_user(CASEY))
    assert body == {"ok": True, "total": 2, "items": SEED_PAIRS, "merges": []}


# ── the matching rule, pair by pair ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("first, second", [
    ("Tallgrass Construction", "Tallgrass Const. LLC"),             # a short form, an ending, a full stop
    ("Smith & Sons Roofing", "Smith and Sons Roofing Corp"),         # "&" and "and", an ending
    ("Kaw-Point Mechanical, Inc.", "Kaw Point Mech"),                # a hyphen, a comma, a short form
    ("Bison Bros. Flooring Ltd.", "Bison Brothers Flooring"),        # a short form inside, an ending
    ("Sunflower Mfg. Co.", "Sunflower Manufacturing Company"),       # both ends spelled two ways
    ("HIGH PLAINS ELECTRIC", "High Plains Electric, L.L.C."),        # case, a dotted ending
    ("Blue Valley Paving", "Blue Valley Paving"),                    # the same name twice
    ("Harbor Point Engineering LLP", "Harbor Point Eng."),           # an ending Add contact's key keeps
])
def test_cleaned_names_that_are_equal_make_a_pair(bd_seeded, bd_db, bd_as_user, first, second):
    a, b = bd_pair(bd_db, first, second)
    assert (a, b) in pairs(bd_as_user(CASEY))


@pytest.mark.parametrize("first, second", [
    ("Midwest Concrete", "Midwest Concrete Coatings"),               # one more word
    ("Summit Builders", "Summit Builders Supply"),
    ("North Star Const.", "North Star Consulting"),                  # a short form is not a prefix match
    ("Acme Inc", "Acme Industries"),                                 # an ending is not a short form
    ("Lone Elm Dental", "Lone Oak Dental"),                          # one word differs
])
def test_names_that_differ_once_cleaned_make_no_pair(bd_seeded, bd_db, bd_as_user, first, second):
    a, b = bd_pair(bd_db, first, second)
    found = pairs(bd_as_user(CASEY))
    assert (a, b) not in found and (b, a) not in found


def test_a_name_with_nothing_left_after_cleaning_never_pairs(bd_seeded, bd_db, bd_as_user):
    a, b = bd_pair(bd_db, "&", "And")
    found = pairs(bd_as_user(CASEY))
    assert all(a not in p and b not in p for p in found)


def test_three_accounts_with_one_cleaned_name_make_three_pairs(bd_seeded, bd_db, bd_as_user):
    ids = [company(bd_db, n) for n in ("Juniper Hollow Dental", "Juniper Hollow Dental LLC", "Juniper Hollow Dental, Inc.")]
    for cid in ids:
        person(bd_db, cid, "Rae Lindgren")
    found = [p for p in pairs(bd_as_user(CASEY)) if p[0] in ids]
    assert found == [(ids[0], ids[1]), (ids[0], ids[2]), (ids[1], ids[2])]


# ── only BD accounts ────────────────────────────────────────────────────────────────────────────
def test_a_pair_is_listed_only_when_one_side_has_a_bd_person(bd_seeded, bd_db, bd_as_user):
    """Likely duplicate BD accounts: one side must be on the BD tab (a BD person not archived), or the
    note would name two accounts the list under it never shows. Worked by hand:
        Evergy Services / Evergy Services Inc      maintenance people only        -> no pair
        Flint Hills Glass / Flint Hills Glass LLC  nobody at either               -> no pair
        Kanza Tile / Kanza Tile Co                 an archived BD person and a
                                                   maintenance person at the first -> no pair
        Wakarusa Stone / Wakarusa Stone LLC        maintenance at the first, a BD
                                                   person at the second           -> a pair, 1 and 1 people"""
    ev = company(bd_db, "Evergy Services"), company(bd_db, "Evergy Services Inc")
    person(bd_db, ev[0], "Ida Moss", category="maintenance")
    person(bd_db, ev[1], "Lou Kemp", category="maintenance")
    flint = company(bd_db, "Flint Hills Glass"), company(bd_db, "Flint Hills Glass LLC")
    kanza = company(bd_db, "Kanza Tile"), company(bd_db, "Kanza Tile Co")
    person(bd_db, kanza[0], "Tom Ashby", archived=True)
    person(bd_db, kanza[0], "Bea Strand", category="maintenance")
    waka = company(bd_db, "Wakarusa Stone"), company(bd_db, "Wakarusa Stone LLC")
    person(bd_db, waka[0], "Cole Imrie", category="maintenance")
    person(bd_db, waka[1], "Dell Okafor", BLAIR)
    body = duplicates(bd_as_user(CASEY))
    assert [(p["a"]["id"], p["b"]["id"]) for p in body["items"]] == [(12, 13), (10, 11), waka]
    assert body["total"] == 3
    assert [(p["a"]["people_count"], p["b"]["people_count"]) for p in body["items"]][2] == (1, 1)
    assert all(x not in p for p in pairs(bd_as_user(CASEY)) for x in ev + flint + kanza)


# ── hints ───────────────────────────────────────────────────────────────────────────────────────
def _pair(client, a, b):
    return next(p for p in duplicates(client)["items"] if (p["a"]["id"], p["b"]["id"]) == (a, b))


def test_a_shared_phone_in_any_format_is_a_hint(bd_seeded, bd_db, bd_as_user):
    a, b = company(bd_db, "Bison Flooring"), company(bd_db, "Bison Flooring LLC")
    person(bd_db, a, "Rae Lindgren", phone="(913) 555-0131", email="rae@bisonflooring.example.com")
    person(bd_db, b, "Tom Ashby", BLAIR, phone="913.555.0131", email="tom@bisonfloors.example.com")
    person(bd_db, b, "Ida Moss", phone="913-555-0132")
    assert _pair(bd_as_user(CASEY), a, b)["hints"] == {"phones": ["+19135550131"], "email_domains": []}


def test_a_shared_email_domain_in_any_case_is_a_hint(bd_seeded, bd_db, bd_as_user):
    a, b = company(bd_db, "Bison Flooring"), company(bd_db, "Bison Flooring LLC")
    person(bd_db, a, "Rae Lindgren", phone="913-555-0133", email="Rae@BisonFlooring.Example.com")
    person(bd_db, b, "Tom Ashby", phone="913-555-0134", email="tom@bisonflooring.example.com")
    assert _pair(bd_as_user(CASEY), a, b)["hints"] == {"phones": [], "email_domains": ["bisonflooring.example.com"]}


def test_a_free_mail_domain_is_never_a_hint(bd_seeded, bd_db, bd_as_user, monkeypatch):
    """The free mail list is fixed in code. Shown with a made-up domain added to it, so no real
    mailbox appears in a test; the list itself is checked below."""
    a, b = company(bd_db, "Bison Flooring"), company(bd_db, "Bison Flooring LLC")
    person(bd_db, a, "Rae Lindgren", email="rae@freemail.example.com")
    person(bd_db, b, "Tom Ashby", email="tom@freemail.example.com")
    casey = bd_as_user(CASEY)
    assert _pair(casey, a, b)["hints"]["email_domains"] == ["freemail.example.com"]
    monkeypatch.setattr(normalize, "FREE_MAIL_DOMAINS", normalize.FREE_MAIL_DOMAINS | {"freemail.example.com"})
    assert _pair(casey, a, b)["hints"] == {"phones": [], "email_domains": []}


@pytest.mark.parametrize("domain", ["gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com", "icloud.com",
                                    "comcast.net", "att.net", "sbcglobal.net"])
def test_the_free_mail_list_holds_the_common_ones(domain):
    assert domain in normalize.FREE_MAIL_DOMAINS


def test_an_archived_persons_phone_or_email_is_no_hint(bd_seeded, bd_db, bd_as_user):
    a, b = company(bd_db, "Bison Flooring"), company(bd_db, "Bison Flooring LLC")
    person(bd_db, a, "Rae Lindgren", phone="913-555-0135", email="rae@bisonflooring.example.com")
    person(bd_db, b, "Tom Ashby", phone="913-555-0135", email="tom@bisonflooring.example.com", archived=True)
    body = _pair(bd_as_user(CASEY), a, b)
    assert body["hints"] == {"phones": [], "email_domains": []}
    assert (body["a"]["people_count"], body["b"]["people_count"]) == (1, 0)


def test_a_hint_alone_never_makes_a_pair(bd_seeded, bd_db, bd_as_user):
    a, b = company(bd_db, "Harbor Lights Storage"), company(bd_db, "Ridgeway Freight")
    person(bd_db, a, "Rae Lindgren", phone="913-555-0136", email="rae@harborlights.example.com")
    person(bd_db, b, "Tom Ashby", phone="913-555-0136", email="tom@harborlights.example.com")
    found = pairs(bd_as_user(CASEY))
    assert (a, b) not in found and found == [(12, 13), (10, 11)]


def test_people_count_counts_every_category_but_not_the_archived(bd_seeded, bd_db, bd_as_user):
    a, b = company(bd_db, "Bison Flooring"), company(bd_db, "Bison Flooring LLC")
    person(bd_db, a, "Rae Lindgren")
    person(bd_db, a, "Ida Moss", category="maintenance")
    person(bd_db, a, "Lou Kemp", archived=True)
    body = _pair(bd_as_user(CASEY), a, b)
    assert body["a"] == {"id": a, "name": "Bison Flooring", "city": "Lenexa", "people_count": 2}
    assert body["b"] == {"id": b, "name": "Bison Flooring LLC", "city": "Lenexa", "people_count": 0}


# ── paging and the query ────────────────────────────────────────────────────────────────────────
def test_limit_and_offset_page_through_the_pairs(bd_seeded, bd_as_user):
    casey = bd_as_user(CASEY)
    assert duplicates(casey, "?limit=1") == {"ok": True, "total": 2, "items": SEED_PAIRS[:1], "merges": []}
    assert duplicates(casey, "?limit=1&offset=1") == {"ok": True, "total": 2, "items": SEED_PAIRS[1:], "merges": []}


def test_a_bad_limit_is_400(bd_seeded, bd_as_user):
    r = bd_as_user(CASEY).get(URL + "?limit=abc")
    assert r.status_code == 400 and r.json()["fields"] == {"limit": "Use a whole number."}


# ── the cleaning itself, word by word ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("name, key", [
    ("Tallgrass Const. LLC", "tallgrassconstruction"),
    ("Cottonwood & Sons Paving", "cottonwoodsonspaving"),
    ("Smith and Sons Roofing Corp", "smithsonsroofing"),
    ("Sunflower Mfg. Co., Inc.", "sunflowermanufacturing"),
    ("  Kaw-Point Mech ", "kawpointmechanical"),
    ("Harbor Point Engineering LLP", "harborpointengineering"),
    ("Inc", "inc"),                         # the last word stays, as normalize_company keeps it
    ("& Co.", "co"),                        # "&" goes; "co" is then the last word, so it stays
    ("And", ""),
    ("&", ""),
])
def test_account_key(name, key):
    assert normalize.account_key(name) == key


@pytest.mark.parametrize("email, domain", [
    ("Rae@BisonFlooring.Example.com", "bisonflooring.example.com"),
    ("  tom@bisonflooring.example.com ", "bisonflooring.example.com"),
    ("no-at-sign.example.com", None), ("", None), (None, None), ("trailing@", None),
])
def test_email_domain(email, domain):
    assert normalize.email_domain(email) == domain
