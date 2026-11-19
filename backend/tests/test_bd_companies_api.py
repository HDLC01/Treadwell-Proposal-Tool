"""The companies routes under /api/bd/ (bd/routers/companies.py), moved from BD's
tests/test_companies_api.py with the contact page and Add contact (#808).

    GET   /api/bd/companies        the type-ahead Add contact uses (behaviour and answer unchanged)
    GET   /api/bd/companies/{id}   one company and its people
    POST  /api/bd/companies        a new company, always
    PATCH /api/bd/companies/{id}   rename, city, industry

BD compared these with its mock API (retired in #806). They now run on the fixture seed
(bd/ops/fixture_seed.py, today Wed 2026-11-04) with the answers worked out here by hand. Its nine
accounts, by their cleaned names (lower case, punctuation and "&" gone, a trailing LLC / Inc / Co
dropped):
    10 Prairie Ridge Builders LLC      prairie ridge builders     Dana 21
    11 Prairie Ridge Builders, Inc.    prairie ridge builders     Rory 22, D. Whitlow 33
    12 Cottonwood & Sons Paving        cottonwood sons paving     Marisa 23
    13 Cottonwood Sons Paving Co.      cottonwood sons paving     Theo 24
    14 Cedar Creek Concrete            cedar creek concrete       Priya 25
    15 Cedar Crest Concrete            cedar crest concrete       Owen 26
    16 Bluestem Logistics              bluestem logistics         Lena 27, Sam 28, Ines 29
    17 Kaw Valley Cold Storage         kaw valley cold storage    Hal 30, Nora 31 (maintenance)
    18 Osage Plains Brewing            osage plains brewing       Wes 32
Everything is made up: example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import pytest

AVERY, BLAIR, CASEY, DEVON, EMERY, FRANKIE = 1, 2, 3, 4, 5, 6
ROLE_IDS = {"salesperson": BLAIR, "assistant": CASEY, "manager": DEVON, "admin": EMERY, "super_admin": FRANKIE}
COMPANY_KEYS = {"id", "name", "city", "industry", "contact_count", "created_at"}
# The list's order: the name in lower case, compared byte by byte (a space before ",", "&" before "s").
BY_NAME = [16, 14, 15, 12, 13, 17, 18, 10, 11]


def is_envelope(body, code):
    return (isinstance(body, dict) and body.get("ok") is False and body.get("error") == code
            and isinstance(body.get("message"), str) and body["message"].strip()
            and body["message"][-1] in ".?!")


def ids(body):
    return [c["id"] for c in body["items"]]


def is_central_ts(value):
    return isinstance(value, str) and value.endswith(("-05:00", "-06:00")) and "T" in value


def without_created(company):
    return {k: v for k, v in company.items() if k != "created_at"}


# ── GET /api/bd/companies: the type-ahead ─────────────────────────────────────────────────────
def test_the_type_ahead_answer(bd_seeded, bd_as_user):
    body = bd_as_user(CASEY).get("/api/bd/companies?q=bluestem").json()
    assert set(body) == {"ok", "total", "items"} and (body["ok"], body["total"]) == (True, 1)
    item = body["items"][0]
    assert set(item) == COMPANY_KEYS and is_central_ts(item["created_at"])
    assert without_created(item) == {"id": 16, "name": "Bluestem Logistics", "city": "Lenexa",
                                     "industry": "Warehousing", "contact_count": 3}


def test_the_whole_list_in_name_order(bd_seeded, bd_as_user):
    body = bd_as_user(DEVON).get("/api/bd/companies").json()
    assert (body["total"], ids(body)) == (9, BY_NAME)
    assert {c["id"]: c["contact_count"] for c in body["items"]} == {
        10: 1, 11: 2, 12: 1, 13: 1, 14: 1, 15: 1, 16: 3, 17: 2, 18: 1}


@pytest.mark.parametrize("q,want", [
    ("ridge", [10, 11]),                     # a later word starts with it
    ("RIDGE", [10, 11]),
    ("prairie ridge builders, inc.", [10, 11]),
    ("idge", []),                            # inside a word: no match
    ("cedar", [14, 15]),
    ("cedar cre", [14, 15]),
    ("cedar creek", [14]),
    ("paving co.", [12, 13]),                # "co" is a company ending: "paving"
    ("cottonwood & sons", [12, 13]),
    ("storage", [17]),
    ("zzz", []),
    ("%25", BY_NAME),                        # punctuation only cleans to nothing: everything
    ("%20", BY_NAME),
])
def test_the_type_ahead_matches_a_word_start_of_the_cleaned_name(bd_seeded, bd_as_user, q, want):
    body = bd_as_user(AVERY).get("/api/bd/companies?q=" + q).json()
    assert (body["total"], ids(body)) == (len(want), want), q


@pytest.mark.parametrize("query,want", [("?limit=3&offset=3", BY_NAME[3:6]), ("?limit=0", BY_NAME),
                                        ("?limit=900", BY_NAME), ("?offset=40", [])])
def test_the_type_ahead_pages(bd_seeded, bd_as_user, query, want):
    body = bd_as_user(AVERY).get("/api/bd/companies" + query).json()
    assert (body["total"], ids(body)) == (9, want)


def test_the_count_leaves_archived_people_out(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("update bd.contacts set archived_at = bd_now() where id = 28")
    item = bd_as_user(CASEY).get("/api/bd/companies?q=bluestem").json()["items"][0]
    assert item["contact_count"] == 2


@pytest.mark.parametrize("query,fields", [("limit=x", {"limit": "Use a whole number."}),
                                          ("offset=-1", {"offset": "Use a whole number from 0."})])
def test_a_bad_list_query(bd_seeded, bd_as_user, query, fields):
    r = bd_as_user(AVERY).get("/api/bd/companies?" + query)
    assert r.status_code == 400 and r.json() == {"ok": False, "error": "bad_request",
                                                 "message": "Some fields need fixing.", "fields": fields}


@pytest.mark.parametrize("who", list(ROLE_IDS.values()) + [AVERY])
def test_every_role_reads_companies(bd_seeded, bd_as_user, who):
    assert bd_as_user(who).get("/api/bd/companies").status_code == 200
    assert bd_as_user(who).get("/api/bd/companies/16").status_code == 200


def test_the_company_routes_need_a_sign_in(bd_seeded, bd_client):
    for method, path in (("GET", "/api/bd/companies"), ("GET", "/api/bd/companies/16"),
                         ("POST", "/api/bd/companies"), ("PATCH", "/api/bd/companies/16")):
        assert bd_client.request(method, path).status_code == 401, (method, path)


# ── GET /api/bd/companies/{id} ────────────────────────────────────────────────────────────────
def test_one_company_and_its_people(bd_seeded, bd_as_user):
    body = bd_as_user(BLAIR).get("/api/bd/companies/16").json()
    assert set(body) == {"ok", "company", "contacts"}
    assert without_created(body["company"]) == {"id": 16, "name": "Bluestem Logistics", "city": "Lenexa",
                                                "industry": "Warehousing", "contact_count": 3}
    assert [c["id"] for c in body["contacts"]] == [27, 28, 29]
    assert body["contacts"][0] == {
        "id": 27, "name": "Lena Ortiz", "title": "Facilities Director",
        "company": {"id": 16, "name": "Bluestem Logistics"}, "phone": "913-555-0107", "phone_e164": "+19135550107",
        "email": "lena.ortiz@bluestem.example.com", "category": "bd", "confirmed": False,
        "lead_source": "Other/Misc", "last_live_at": None, "cadence_status": "never"}


def test_a_company_page_shows_its_maintenance_people_too(bd_seeded, bd_as_user):
    body = bd_as_user(BLAIR).get("/api/bd/companies/17").json()
    assert [(c["id"], c["category"]) for c in body["contacts"]] == [(30, "maintenance"), (31, "maintenance")]
    assert body["contacts"][0]["last_live_at"] == "2026-08-20T10:00:00-05:00"


def test_a_company_page_leaves_archived_people_out(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("update bd.contacts set archived_at = bd_now() where id = 22")
    body = bd_as_user(BLAIR).get("/api/bd/companies/11").json()
    assert [c["id"] for c in body["contacts"]] == [33] and body["company"]["contact_count"] == 1


@pytest.mark.parametrize("path", ["/api/bd/companies/999", "/api/bd/companies/0",
                                  "/api/bd/companies/99999999999999999999", "/api/bd/companies/abc",
                                  "/api/bd/companies/%205"])
def test_ids_that_name_no_company_are_404(bd_seeded, bd_as_user, path):
    r = bd_as_user(BLAIR).get(path)
    assert r.status_code == 404 and r.json() == {"ok": False, "error": "not_found",
                                                 "message": "That company does not exist."}


# ── POST /api/bd/companies ────────────────────────────────────────────────────────────────────
def test_a_new_company(bd_seeded, bd_as_user, bd_db):
    """The fixture's last company is 18, so this is 19. The name is stored cleaned."""
    r = bd_as_user(BLAIR).post("/api/bd/companies", json={"name": "  Juniper Hollow  Dental ", "city": "Lenexa",
                                                          "industry": "Healthcare"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"ok", "company", "possible_duplicates"} and body["possible_duplicates"] == []
    assert set(body["company"]) == COMPANY_KEYS and body["company"]["created_at"].startswith("2026-11-04T")
    assert without_created(body["company"]) == {"id": 19, "name": "Juniper Hollow Dental", "city": "Lenexa",
                                                "industry": "Healthcare", "contact_count": 0}
    row = bd_db.execute("select name, normalized_name from bd.companies where id = 19").fetchone()
    assert row == {"name": "Juniper Hollow Dental", "normalized_name": "juniper hollow dental"}
    # The type-ahead finds it at once.
    assert ids(bd_as_user(BLAIR).get("/api/bd/companies?q=juniper").json()) == [19]


def test_a_new_company_with_a_known_name_lists_the_people_already_there(bd_seeded, bd_as_user, bd_db):
    """POST always makes a new company (merging accounts is a later ticket); the people at the
    accounts with the same cleaned name come back as a hint."""
    body = bd_as_user(CASEY).post("/api/bd/companies", json={"name": "PRAIRIE RIDGE BUILDERS"}).json()
    assert [(d["contact_id"], d["reason"]) for d in body["possible_duplicates"]] == [
        (21, "Same company name"), (22, "Same company name"), (33, "Same company name")]
    assert (body["company"]["id"], body["company"]["contact_count"]) == (19, 0)
    assert bd_db.execute("select count(*) as n from bd.companies where normalized_name = 'prairie ridge builders'"
                         ).fetchone()["n"] == 3


@pytest.mark.parametrize("body,message,fields", [
    ({}, "Type the company name.", {"name": "Required."}),
    ({"name": "   "}, "Type the company name.", {"name": "Required."}),
    ({"name": 5}, "Type the company name.", {"name": "Required."}),
    ({"name": "X", "city": 5}, "Some fields need fixing.", {"city": "Use text."}),
    ({"name": "X", "industry": ["a"]}, "Some fields need fixing.", {"industry": "Use text."}),
    (["Juniper"], "Some fields need fixing.", {"body": "Send a JSON object."}),
])
def test_create_validation(bd_seeded, bd_as_user, bd_db, body, message, fields):
    r = bd_as_user(BLAIR).post("/api/bd/companies", json=body)
    assert r.status_code == 400 and r.json() == {"ok": False, "error": "bad_request", "message": message,
                                                 "fields": fields}, r.text
    assert bd_db.execute("select count(*) as n from bd.companies").fetchone()["n"] == 9


@pytest.mark.parametrize("role,allowed", [("salesperson", True), ("assistant", True), ("manager", False),
                                          ("admin", True), ("super_admin", True)])
def test_create_roles(bd_seeded, bd_as_user, role, allowed):
    r = bd_as_user(ROLE_IDS[role]).post("/api/bd/companies", json={"name": "Role Co " + role})
    assert r.status_code == (201 if allowed else 403)
    if not allowed:
        assert r.json() == {"ok": False, "error": "forbidden", "message": "Your role can't do that."}


# ── PATCH /api/bd/companies/{id} ──────────────────────────────────────────────────────────────
def test_a_rename_reaches_the_duplicate_check_the_people_and_add_contact(bd_seeded, bd_as_user, bd_db):
    c = bd_as_user(CASEY)
    r = c.patch("/api/bd/companies/15", json={"name": " Cedar Crest  Concrete Supply LLC "})
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"ok", "company"}
    assert without_created(r.json()["company"]) == {"id": 15, "name": "Cedar Crest Concrete Supply LLC",
                                                    "city": "Lawrence", "industry": "Concrete", "contact_count": 1}
    assert bd_db.execute("select normalized_name from bd.companies where id = 15").fetchone()["normalized_name"] == \
        "cedar crest concrete supply"
    assert c.get("/api/bd/contacts/26").json()["contact"]["company"] == {"id": 15,
                                                                         "name": "Cedar Crest Concrete Supply LLC"}
    dups = c.get("/api/bd/contacts/duplicates?company=cedar%20crest%20concrete%20supply").json()["items"]
    assert [d["contact_id"] for d in dups] == [26]
    assert c.get("/api/bd/contacts/duplicates?company=Cedar%20Crest%20Concrete").json()["items"] == []
    added = c.post("/api/bd/contacts", json={"company": {"name": "cedar crest concrete supply"}, "name": "Al Ruiz"})
    assert added.json()["contact"]["company"]["id"] == 15


def test_city_and_industry_change_and_clear(bd_seeded, bd_as_user):
    r = bd_as_user(BLAIR).patch("/api/bd/companies/18", json={"city": "Wamego", "industry": None})
    assert without_created(r.json()["company"]) == {"id": 18, "name": "Osage Plains Brewing", "city": "Wamego",
                                                    "industry": None, "contact_count": 1}
    r = bd_as_user(BLAIR).patch("/api/bd/companies/18", json={})
    assert r.status_code == 200 and r.json()["company"]["city"] == "Wamego"


@pytest.mark.parametrize("role,allowed", [("salesperson", True), ("assistant", True), ("manager", False),
                                          ("admin", True), ("super_admin", True)])
def test_patch_roles(bd_seeded, bd_as_user, bd_db, role, allowed):
    r = bd_as_user(ROLE_IDS[role]).patch("/api/bd/companies/14", json={"city": "Eudora"})
    assert r.status_code == (200 if allowed else 403)
    assert (bd_db.execute("select city from bd.companies where id = 14").fetchone()["city"] == "Eudora") == allowed


def test_patch_errors(bd_seeded, bd_as_user, bd_db):
    r = bd_as_user(BLAIR).patch("/api/bd/companies/999", json={"city": "x"})
    assert r.status_code == 404 and r.json()["message"] == "That company does not exist."
    r = bd_as_user(BLAIR).patch("/api/bd/companies/14", json={"name": None})
    assert r.status_code == 400 and r.json() == {"ok": False, "error": "bad_request",
                                                 "message": "A company needs a name.", "fields": {"name": "Required."}}
    r = bd_as_user(BLAIR).patch("/api/bd/companies/14", json={"name": " "})
    assert r.status_code == 400 and r.json()["fields"] == {"name": "Required."}
    r = bd_as_user(BLAIR).patch("/api/bd/companies/14", json={"city": 3})
    assert r.status_code == 400 and r.json()["fields"] == {"city": "Use text."}
    r = bd_as_user(BLAIR).patch("/api/bd/companies/14", json="Cedar")
    assert r.status_code == 400 and r.json()["fields"] == {"body": "Send a JSON object."}
    r = bd_as_user(BLAIR).patch("/api/bd/companies/14", content=b"[", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and is_envelope(r.json(), "bad_request")
    assert bd_db.execute("select name, city from bd.companies where id = 14").fetchone() == {
        "name": "Cedar Creek Concrete", "city": "Lawrence"}
