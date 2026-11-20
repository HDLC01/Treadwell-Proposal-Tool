"""Merging two BD accounts, Undo, and Keep separate (#811).

    POST /api/bd/contacts/accounts/{id}/merge          {"into": survivor id, "name_from": either id}
    POST /api/bd/contacts/accounts/merges/{id}/undo    the merge's id, from the merge's answer
    POST /api/bd/contacts/accounts/duplicates/keep     {"accounts": [id, id]}

Worked by hand on the fixture seed (bd/ops/fixture_seed.py), today Wed 2026-11-04:
    10 Prairie Ridge Builders LLC     Dana 21 (Avery's): calls 101 and 102, open follow-up 302 on Avery's
                                      list, recommendation 401, candidate 601
    11 Prairie Ridge Builders, Inc.   Rory 22 and D. Whitlow 33 (both Blair's)
    12 Cottonwood & Sons Paving       Marisa 23 (Avery's)
    13 Cottonwood Sons Paving Co.     Theo 24 (Blair's)
THE MAIN CASE: Casey (the assistant) merges 10 into 11 and keeps 10's name. Dana moves to 11 and stays
Avery's; her calls, task and recommendation still point at her. 11 is renamed "Prairie Ridge Builders
LLC" and now has 3 people, 2 of them Blair's, so the BD tab shows Blair "+1". 10 is marked merged into
11 by Casey, and is gone from the list, search and the type-ahead. One company_merged event holds
ids and names of accounts only. Undo puts Dana back on 10, 11's old name back and clears the mark;
anyone added at 11 after the merge stays there.
Everything is made up: example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import io
import threading
import time

import pytest

from bd import normalize

AVERY, BLAIR, CASEY, DEVON, EMERY, FRANKIE = 1, 2, 3, 4, 5, 6
MERGE = "/api/bd/contacts/accounts/%s/merge"
UNDO = "/api/bd/contacts/accounts/merges/%s/undo"
KEEP = "/api/bd/contacts/accounts/duplicates/keep"
DUPES = "/api/bd/contacts/accounts/duplicates"

CHANGED = "Something changed since this merge, so it can't be undone."


# ── made-up data and what the database holds ────────────────────────────────────────────────────
def company(db, name, city="Lenexa"):
    return db.execute("insert into bd.companies (name, normalized_name, city) values (%s, %s, %s) returning id",
                      (name, normalize.normalize_company(name), city)).fetchone()["id"]


def person(db, company_id, name, owner=AVERY, category="bd", archived=False):
    return db.execute(
        "insert into bd.contacts (company_id, name, owner_id, category, archived_at)"
        " values (%s, %s, %s, %s, case when %s then bd_now() end) returning id",
        (company_id, name, owner, category, archived)).fetchone()["id"]


def state(db):
    """Everything a merge, an undo or a keep may touch, as plain values."""
    return db.execute(
        "select (select json_agg(c order by c.id) from (select id, name, normalized_name, city, industry,"
        "   merged_into, merged_at, merged_by from bd.companies) c) as companies,"
        " (select json_agg(c order by c.id) from (select id, company_id, owner_id, co_owner_id, category,"
        "   archived_at, frequency_per_year from bd.contacts) c) as contacts,"
        " (select json_agg(i order by i.id) from (select id, contact_id, user_id from bd.interactions) i) as interactions,"
        " (select json_agg(t order by t.id) from (select id, contact_id, batch_id, status from bd.tasks) t) as tasks,"
        " (select json_agg(k order by k.account_a, k.account_b) from bd.account_pairs_kept k) as kept,"
        " (select json_agg(e order by e.id) from (select id, kind, actor_id, contact_id, data from bd.events) e)"
        "   as events").fetchone()


def merge(client, loser, into, name_from=None, status=200):
    r = client.post(MERGE % loser, json={"into": into, "name_from": loser if name_from is None else name_from})
    assert r.status_code == status, r.text
    return r.json()


def merged(client, loser, into, name_from=None):
    return merge(client, loser, into, name_from)["merge"]


def company_row(db, cid):
    return db.execute("select name, normalized_name, merged_into, merged_by, merged_at from bd.companies"
                      " where id = %s", (cid,)).fetchone()


# ── merge ────────────────────────────────────────────────────────────────────────────────────────
def test_merge_moves_the_people_keeps_their_owners_and_uses_the_picked_name(bd_seeded, bd_as_user, bd_db):
    before = state(bd_db)
    body = merge(bd_as_user(CASEY), 10, 11, name_from=10)
    m = body["merge"]
    assert set(m) == {"id", "account", "into", "name_before", "people", "people_count", "at", "by"}
    assert {k: m[k] for k in ("account", "into", "name_before", "people", "people_count", "by")} == {
        "account": {"id": 10, "name": "Prairie Ridge Builders LLC"},
        "into": {"id": 11, "name": "Prairie Ridge Builders LLC"},
        "name_before": "Prairie Ridge Builders, Inc.", "people": 1, "people_count": 3,
        "by": {"id": CASEY, "name": "Casey Moret"}}
    from bd import serialize

    at = bd_db.execute("select at from bd.events where id = %s", (m["id"],)).fetchone()["at"]
    assert m["at"] == serialize.ts(at)
    after = state(bd_db)
    contacts = {c["id"]: c for c in after["contacts"]}
    assert contacts[21]["company_id"] == 11 and contacts[21]["owner_id"] == AVERY
    assert [c for c in after["contacts"] if c["id"] != 21] == [c for c in before["contacts"] if c["id"] != 21]
    assert after["interactions"] == before["interactions"] and after["tasks"] == before["tasks"]
    survivor, loser = company_row(bd_db, 11), company_row(bd_db, 10)
    assert (survivor["name"], survivor["normalized_name"], survivor["merged_into"]) == (
        "Prairie Ridge Builders LLC", "prairie ridge builders", None)
    assert (loser["name"], loser["merged_into"], loser["merged_by"]) == ("Prairie Ridge Builders LLC", 11, CASEY)
    assert loser["merged_at"] == at


def test_the_survivors_own_name_is_kept_when_it_is_picked(bd_seeded, bd_as_user, bd_db):
    m = merged(bd_as_user(CASEY), 10, 11, name_from=11)
    assert m["into"] == {"id": 11, "name": "Prairie Ridge Builders, Inc."}
    assert m["name_before"] == "Prairie Ridge Builders, Inc."
    assert company_row(bd_db, 11)["name"] == "Prairie Ridge Builders, Inc."


def test_every_person_moves_bd_maintenance_and_archived_each_with_their_owner(bd_seeded, bd_as_user, bd_db):
    a, b = company(bd_db, "Tallgrass Millwork"), company(bd_db, "Tallgrass Millwork LLC")
    p1 = person(bd_db, a, "Arlo Penn", AVERY)
    p2 = person(bd_db, a, "Bea Strand", BLAIR, category="maintenance")
    p3 = person(bd_db, a, "Cole Imrie", DEVON, archived=True)
    q1 = person(bd_db, b, "Dell Okafor", BLAIR)
    m = merged(bd_as_user(EMERY), a, b, name_from=b)
    assert (m["people"], m["people_count"]) == (2, 3)            # p3 moved, but is archived
    rows = {r["id"]: r for r in bd_db.execute(
        "select id, company_id, owner_id, category, archived_at is not null as archived from bd.contacts"
        " where id = any(%s)", ([p1, p2, p3, q1],))}
    assert {i: (r["company_id"], r["owner_id"], r["category"], r["archived"]) for i, r in rows.items()} == {
        p1: (b, AVERY, "bd", False), p2: (b, BLAIR, "maintenance", False), p3: (b, DEVON, "bd", True),
        q1: (b, BLAIR, "bd", False)}


def test_one_event_holds_ids_and_names_of_accounts_only(bd_seeded, bd_as_user, bd_db):
    m = merged(bd_as_user(CASEY), 10, 11, name_from=10)
    ev = bd_db.execute("select kind, actor_id, contact_id, detail, data from bd.events where id = %s",
                       (m["id"],)).fetchone()
    assert ev == {"kind": "company_merged", "actor_id": CASEY, "contact_id": None, "detail": None, "data": {
        "company_id": 10, "into": 11, "name_from": 10, "name_before": "Prairie Ridge Builders, Inc.",
        "name_after": "Prairie Ridge Builders LLC", "contacts": [21], "people": 1}}
    assert bd_db.execute("select count(*) as n from bd.events").fetchone()["n"] == 1


def test_the_merge_is_one_transaction(bd_seeded, bd_as_user, bd_db, monkeypatch):
    """A failure at the last step (writing the event) leaves nothing of the merge behind."""
    from bd.routers import account_merge

    def broken(*_a, **_k):
        raise RuntimeError("made-up failure")

    before = state(bd_db)
    monkeypatch.setattr(account_merge, "log_event", broken)
    r = bd_as_user(CASEY).post(MERGE % 10, json={"into": 11, "name_from": 10})
    assert r.status_code == 500
    assert state(bd_db) == before


def test_the_merge_waits_for_a_lock_on_either_account(bd_seeded, bd_as_user, bd_db_url):
    """It locks both companies before it reads them: a merge started while another session is
    changing the survivor's row waits for it. The survivor keeps its name here, so the merge never
    writes that row; only the merge's own lock can make it wait (moving a person checks the row with
    a key-share lock, which an edit of the row's city does not block)."""
    import _bd_db

    done = []
    casey = bd_as_user(CASEY)
    with _bd_db.connect(bd_db_url, autocommit=False) as holder:
        holder.execute("update bd.companies set city = city where id = 11")
        t = threading.Thread(target=lambda: done.append(
            casey.post(MERGE % 10, json={"into": 11, "name_from": 11}).status_code), daemon=True)
        t.start()
        time.sleep(0.8)
        assert done == [], "the merge went ahead while another session held the survivor"
        holder.rollback()
    t.join(30)
    assert done == [200]


def _during_a_merge(monkeypatch, client, loser, into, name_from, other):
    """Run `other()` in a thread while a real merge of `loser` into `into` is open (it has moved the
    people and set the mark, and holds its locks, but has not committed), then let the merge commit.
    Returns what `other()` returned. `other` must WAIT for the merge: it may not finish first."""
    from bd.routers import account_merge

    real, go, inside = account_merge.log_event, threading.Event(), threading.Event()

    def held(*a, **k):
        inside.set()
        assert go.wait(30), "the test never let the merge go on"
        return real(*a, **k)

    monkeypatch.setattr(account_merge, "log_event", held)
    merging, got = [], []
    m = threading.Thread(target=lambda: merging.append(client.post(
        MERGE % loser, json={"into": into, "name_from": name_from}).status_code), daemon=True)
    m.start()
    assert inside.wait(30), "the merge never reached its last step"
    o = threading.Thread(target=lambda: got.append(other()), daemon=True)
    o.start()
    time.sleep(0.8)
    early = list(got)
    go.set()
    m.join(30)
    o.join(30)
    assert merging == [200]
    assert early == [], "it went ahead while the merge held the account, so the race was never run"
    return got[0]


@pytest.mark.parametrize("spec", [{"id": 10}, {"name": "Prairie Ridge Builders LLC"}], ids=["by-id", "by-name"])
def test_a_person_added_while_a_merge_runs_lands_on_the_survivor(bd_seeded, bd_as_user, bd_db, monkeypatch, spec):
    """Add contact read the losing account before the merge committed: it must wait for the merge and
    then follow it, never write the person onto the hidden account."""
    casey = bd_as_user(CASEY)

    def add():
        r = casey.post("/api/bd/contacts", json={"name": "Nell Brandt", "company": spec})
        return r.status_code, r.json()["contact"]["company"]["id"] if r.status_code == 201 else r.text

    assert _during_a_merge(monkeypatch, casey, 10, 11, 11, add) == (201, 11)
    assert bd_db.execute("select company_id from bd.contacts where name = 'Nell Brandt'").fetchone()["company_id"] == 11
    assert bd_db.execute("select count(*) as n from bd.contacts where company_id = 10").fetchone()["n"] == 0


def test_an_import_that_read_the_accounts_before_a_merge_puts_its_people_on_the_survivor(
        bd_seeded, bd_as_user, bd_db, monkeypatch):
    """The importer remembers each account by name when it starts. A merge that commits while the run
    is going must not leave that memory pointing at the hidden account."""
    casey = bd_as_user(CASEY)
    csv = b"Company,Name,Email\nCottonwood & Sons Paving,Nell Brandt,nell@cottonwoodpaving.example.com\n"

    def run_import():
        r = casey.post("/api/bd/admin/import", files={"file": ("people.csv", io.BytesIO(csv), "text/csv")},
                       data={"dry_run": "false"})
        return r.status_code

    assert _during_a_merge(monkeypatch, casey, 12, 13, 13, run_import) == 200
    row = bd_db.execute("select company_id from bd.contacts where name = 'Nell Brandt'").fetchone()
    assert row["company_id"] == 13


# ── hidden from the list, search and the type-ahead ─────────────────────────────────────────────
def test_a_merged_account_leaves_the_bd_tab_and_the_survivor_counts_everyone(bd_seeded, bd_as_user):
    devon = bd_as_user(DEVON)
    rows = {a["id"]: a for a in devon.get("/api/bd/contacts/accounts").json()["items"]}
    assert 10 in rows and rows[11]["people_count"] == 2
    merge(bd_as_user(CASEY), 10, 11, name_from=10)
    rows = {a["id"]: a for a in devon.get("/api/bd/contacts/accounts").json()["items"]}
    assert 10 not in rows
    assert (rows[11]["name"], rows[11]["people_count"], rows[11]["owner"], rows[11]["other_owners"]) == (
        "Prairie Ridge Builders LLC", 3, {"id": BLAIR, "name": "Blair Fenn"}, 1)
    assert [p["id"] for p in rows[11]["people"]] == [33, 21, 22]      # D. Whitlow, Dana, Rory by name


def test_a_merged_account_leaves_search(bd_seeded, bd_as_user):
    devon = bd_as_user(DEVON)

    def hits(q):
        return [(i["account"]["id"], [p["id"] for p in i["people"]])
                for i in devon.get("/api/bd/contacts/search", params={"q": q}).json()["items"]]

    assert hits("dana") == [(10, [21]), (11, [33])]
    assert hits("prairie ridge") == [(10, []), (11, [])]          # the account names match, nobody's
    merge(bd_as_user(CASEY), 10, 11, name_from=11)
    assert hits("dana") == [(11, [33, 21])]
    assert hits("prairie ridge") == [(11, [])]


TYPE_AHEAD = (b'{"ok":true,"total":1,"items":[{"id":16,"name":"Bluestem Logistics","city":"Lenexa",'
              b'"industry":"Warehousing","created_at":"2026-11-04T09:00:00-06:00","contact_count":3}]}')


def test_a_merged_account_leaves_the_type_ahead_and_the_rest_answers_as_before(bd_seeded, bd_as_user, bd_db):
    import json

    bd_db.execute("update bd.companies set created_at = '2026-11-04 15:00:00+00'")
    casey = bd_as_user(CASEY)
    assert casey.get("/api/bd/companies?q=bluestem").content == TYPE_AHEAD
    whole = json.loads(casey.get("/api/bd/companies").content)
    assert [c["id"] for c in casey.get("/api/bd/companies?q=cottonwood").json()["items"]] == [12, 13]
    merge(casey, 12, 13, name_from=13)
    assert casey.get("/api/bd/companies?q=bluestem").content == TYPE_AHEAD
    assert casey.get("/api/bd/companies?q=cottonwood").json() == {"ok": True, "total": 1, "items": [
        dict(next(c for c in whole["items"] if c["id"] == 13), contact_count=2)]}
    after = json.loads(casey.get("/api/bd/companies").content)
    assert after["total"] == whole["total"] - 1
    assert [c for c in after["items"] if c["id"] != 13] == [c for c in whole["items"] if c["id"] not in (12, 13)]


def test_a_person_added_by_a_merged_accounts_name_or_id_lands_on_the_survivor(bd_seeded, bd_as_user, bd_db):
    """Add contact finds a company by its cleaned name, or takes its id. A merged-away account is
    hidden, so a person must never land on it: they go to the account it was merged into."""
    casey = bd_as_user(CASEY)
    a = company(bd_db, "Tallgrass Const. LLC")           # cleaned for Add contact: "tallgrass const"
    b = company(bd_db, "Tallgrass Construction")         # "tallgrass construction"
    merge(casey, a, b, name_from=b)
    merge(casey, 12, 13, name_from=13)                   # both clean to "cottonwood sons paving"

    def added(spec):
        r = casey.post("/api/bd/contacts", json={"name": "Nell Brandt", "company": spec})
        assert r.status_code == 201, r.text
        return r.json()["contact"]["company"]["id"]

    assert added({"name": "Tallgrass Const"}) == b       # only the merged-away account has that name
    assert added({"id": a}) == b
    assert added({"name": "Cottonwood & Sons Paving"}) == 13    # the live one wins over the merged one
    assert added({"id": 12}) == 13
    c = company(bd_db, "Tallgrass Const")                # a live account with the merged one's name
    assert added({"name": "Tallgrass Const"}) == c       # wins over following the merged one to b
    assert bd_db.execute("select count(*) as n from bd.contacts where company_id = any(%s)",
                         ([a, 12],)).fetchone()["n"] == 0
    assert added({"id": a}) == b                         # an id still leads where its merge went


def _tallgrass(db):
    """Two accounts whose cleaned names differ ("tallgrass const" and "tallgrass construction"), one
    made-up person at each: Wren Hale at a, Opal Hale at b."""
    a = company(db, "Tallgrass Const. LLC")
    b = company(db, "Tallgrass Construction")
    return a, b, person(db, a, "Wren Hale"), person(db, b, "Opal Hale")


def _same_name(client, company_name):
    r = client.get("/api/bd/contacts/duplicates", params={"company": company_name})
    assert r.status_code == 200, r.text
    return [(m["contact_id"], m["company"], m["reason"]) for m in r.json()["items"]]


def test_add_contacts_same_name_warning_names_everyone_at_the_account_the_name_leads_to(bd_seeded, bd_as_user, bd_db):
    """Before the merge, "Tallgrass Const. LLC" warns of Wren. After it, that name leads to b, which
    holds Wren and Opal, so the person adding a third sees both (verifier, #811)."""
    casey = bd_as_user(CASEY)
    a, b, wren, opal = _tallgrass(bd_db)
    assert _same_name(casey, "Tallgrass Const. LLC") == [(wren, "Tallgrass Const. LLC", "Same company name")]
    merge(casey, a, b, name_from=b)
    both = [(wren, "Tallgrass Construction", "Same company name"), (opal, "Tallgrass Construction", "Same company name")]
    assert _same_name(casey, "Tallgrass Const. LLC") == both
    r = casey.post("/api/bd/contacts", json={"name": "Nell Brandt", "company": {"name": "Tallgrass Const. LLC"}})
    assert r.status_code == 201, r.text
    assert r.json()["contact"]["company"]["id"] == b
    assert [(m["contact_id"], m["reason"]) for m in r.json()["possible_duplicates"]] == [
        (wren, "Same company name"), (opal, "Same company name")]
    assert r.json()["contact"]["duplicate_of"]["contact_id"] == wren


def test_the_survivors_old_name_still_leads_to_it_after_a_merge_renamed_it(bd_seeded, bd_as_user, bd_db):
    """Merging a into b and keeping a's name renames b "Tallgrass Const. LLC". Its old name,
    "Tallgrass Construction", must still lead to b: Add contact, the warning and the import put the
    person there and make no new account (verifier, #811)."""
    casey = bd_as_user(CASEY)
    a, b, wren, opal = _tallgrass(bd_db)
    merge(casey, a, b, name_from=a)
    assert company_row(bd_db, b)["name"] == "Tallgrass Const. LLC"
    accounts = bd_db.execute("select count(*) as n from bd.companies").fetchone()["n"]
    assert [m[0] for m in _same_name(casey, "Tallgrass Construction")] == [wren, opal]
    r = casey.post("/api/bd/contacts", json={"name": "Nell Brandt", "company": {"name": "Tallgrass Construction"}})
    assert r.status_code == 201, r.text
    assert r.json()["contact"]["company"]["id"] == b
    csv = b"Company,Name,Email\nTallgrass Construction,Ruth Ober,ruth@tallgrass.example.com\n"
    r = casey.post("/api/bd/admin/import", files={"file": ("people.csv", io.BytesIO(csv), "text/csv")},
                   data={"dry_run": "false"})
    assert r.status_code == 200, r.text
    assert bd_db.execute("select company_id from bd.contacts where name = 'Ruth Ober'").fetchone()["company_id"] == b
    assert bd_db.execute("select count(*) as n from bd.companies").fetchone()["n"] == accounts


def test_an_undone_renaming_merge_leaves_no_trail_and_a_live_account_wins_over_one(bd_seeded, bd_as_user, bd_db):
    """After Undo the merge never happened: renaming b by hand afterwards frees its old name, so Add
    contact by that name makes a new account. And while a renaming merge stands, an account that
    really has the old name is the one a person joins."""
    casey = bd_as_user(CASEY)
    a, b, _wren, _opal = _tallgrass(bd_db)
    m = merged(casey, a, b, name_from=a)
    assert casey.post(UNDO % m["id"], json={}).status_code == 200
    assert casey.patch("/api/bd/companies/%s" % b, json={"name": "Tallgrass Group"}).status_code == 200

    def added(name):
        r = casey.post("/api/bd/contacts", json={"name": "Nell Brandt", "company": {"name": name}})
        assert r.status_code == 201, r.text
        return r.json()["contact"]["company"]["id"]

    fresh = added("Tallgrass Construction")
    assert fresh not in (a, b)
    c, d = company(bd_db, "Bluff Road Paving Inc."), company(bd_db, "Bluff Rd Paving")
    merge(casey, c, d, name_from=c)                     # d is now "Bluff Road Paving Inc."
    e = company(bd_db, "Bluff Rd Paving")
    assert added("Bluff Rd Paving") == e


@pytest.mark.parametrize("user", [AVERY, CASEY])
def test_a_merged_away_account_cannot_be_edited(bd_seeded, bd_as_user, bd_db, user):
    """It is hidden and frozen until Undo, so Undo brings it back as it was (verifier, #811)."""
    merge(bd_as_user(CASEY), 13, 12, name_from=12)
    before = state(bd_db)
    for body in ({"name": "Renamed Hidden Co"}, {"city": "Olathe"}, {}):
        r = bd_as_user(user).patch("/api/bd/companies/13", json=body)
        assert (r.status_code, r.json()["message"]) == (409, "This account is already merged into another."), r.text
    assert state(bd_db) == before
    assert bd_as_user(user).patch("/api/bd/companies/12", json={"city": "Olathe"}).status_code == 200


def test_an_import_never_puts_a_person_on_a_merged_account(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    merge(casey, 12, 13, name_from=13)
    csv = b"Company,Name,Email\nCottonwood & Sons Paving,Nell Brandt,nell@cottonwoodpaving.example.com\n"
    r = casey.post("/api/bd/admin/import", files={"file": ("people.csv", io.BytesIO(csv), "text/csv")},
                   data={"dry_run": "false"})
    assert r.status_code == 200, r.text
    row = bd_db.execute("select company_id from bd.contacts where name = 'Nell Brandt'").fetchone()
    assert row["company_id"] == 13


# ── refused merges change nothing ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("loser, body, status, message, fields", [
    (10, {"into": 10, "name_from": 10}, 400, "Some fields need fixing.", {"into": "Pick another account."}),
    (10, {"name_from": 10}, 400, "Some fields need fixing.", {"into": "Pick the account to merge into."}),
    (10, {"into": "11", "name_from": 10}, 400, "Some fields need fixing.", {"into": "Pick the account to merge into."}),
    (10, {"into": 11}, 400, "Some fields need fixing.", {"name_from": "Pick one of the two names."}),
    (10, {"into": 11, "name_from": 12}, 400, "Some fields need fixing.", {"name_from": "Pick one of the two names."}),
    (10, ["into", 11], 400, "Some fields need fixing.", {"body": "Send a JSON object."}),
    (999999, {"into": 11, "name_from": 11}, 404, "That company does not exist.", None),
    (10, {"into": 999999, "name_from": 10}, 404, "That company does not exist.", None),
    ("abc", {"into": 11, "name_from": 11}, 404, "That company does not exist.", None),
])
def test_a_bad_merge_is_refused_and_changes_nothing(bd_seeded, bd_as_user, bd_db, loser, body, status, message, fields):
    before = state(bd_db)
    r = bd_as_user(CASEY).post(MERGE % loser, json=body)
    assert r.status_code == status, r.text
    assert r.json()["message"] == message and r.json().get("fields") == fields
    assert state(bd_db) == before


def test_a_whole_number_sent_as_11_0_names_account_11_as_add_contact_reads_it(bd_seeded, bd_as_user, bd_db):
    r = bd_as_user(CASEY).post(MERGE % 10, json={"into": 11.0, "name_from": 11.0})
    assert r.status_code == 200, r.text
    assert (r.json()["merge"]["into"], company_row(bd_db, 10)["merged_into"]) == (
        {"id": 11, "name": "Prairie Ridge Builders, Inc."}, 11)


def test_a_merged_account_cannot_be_merged_again_or_merged_into(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    merge(casey, 12, 13, name_from=13)
    before = state(bd_db)
    for loser, into, message in ((12, 10, "This account is already merged into another."),
                                 (10, 12, "That account was merged into another, so nothing can merge into it.")):
        r = casey.post(MERGE % loser, json={"into": into, "name_from": into})
        assert (r.status_code, r.json()["message"]) == (409, message), r.text
    assert state(bd_db) == before


# ── undo ─────────────────────────────────────────────────────────────────────────────────────────
def test_undo_restores_the_people_the_name_and_the_mark_and_later_people_stay(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    before = state(bd_db)
    m = merged(casey, 10, 11, name_from=10)
    r = casey.post("/api/bd/contacts", json={"name": "Nell Brandt", "company": {"id": 11}})
    assert r.status_code == 201, r.text
    nell = r.json()["contact"]["id"]
    events_before_undo = bd_db.execute("select count(*) as n from bd.events").fetchone()["n"]
    r = bd_as_user(EMERY).post(UNDO % m["id"], json={})          # anyone who may merge may undo
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "undone": {"id": m["id"], "account": {"id": 10, "name": "Prairie Ridge Builders LLC"},
                                               "into": {"id": 11, "name": "Prairie Ridge Builders, Inc."}, "people": 1}}
    after = state(bd_db)
    assert after["companies"] == before["companies"]
    assert [c for c in after["contacts"] if c["id"] != nell] == before["contacts"]
    assert next(c for c in after["contacts"] if c["id"] == nell)["company_id"] == 11
    ev = bd_db.execute("select kind, actor_id, contact_id, data from bd.events order by id desc limit 1").fetchone()
    assert ev == {"kind": "company_merge_undone", "actor_id": EMERY, "contact_id": None,
                  "data": {"merge_id": m["id"], "company_id": 10, "into": 11, "people": 1}}
    assert bd_db.execute("select count(*) as n from bd.events").fetchone()["n"] == events_before_undo + 1


def test_after_undo_the_pair_is_listed_again_and_the_merge_leaves_the_recent_list(bd_seeded, bd_as_user):
    casey = bd_as_user(CASEY)
    m = merged(casey, 12, 13, name_from=13)
    body = casey.get(DUPES).json()
    assert [(p["a"]["id"], p["b"]["id"]) for p in body["items"]] == [(10, 11)]
    assert [x["id"] for x in body["merges"]] == [m["id"]]
    assert casey.post(UNDO % m["id"], json={}).status_code == 200
    body = casey.get(DUPES).json()
    assert [(p["a"]["id"], p["b"]["id"]) for p in body["items"]] == [(12, 13), (10, 11)]
    assert body["merges"] == []


def test_undo_has_no_time_limit(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    m = merged(casey, 12, 13)
    bd_db.execute("update bd.events set at = at - interval '400 days' where id = %s", (m["id"],))
    bd_db.execute("update bd.companies set merged_at = merged_at - interval '400 days' where id = 12")
    assert casey.post(UNDO % m["id"], json={}).status_code == 200
    assert company_row(bd_db, 12)["merged_into"] is None


def _refused(client, db, merge_id, status, message):
    before = state(db)
    r = client.post(UNDO % merge_id, json={})
    assert (r.status_code, r.json()["message"]) == (status, message), r.text
    assert state(db) == before


def test_undo_twice_is_refused(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    m = merged(casey, 12, 13)
    assert casey.post(UNDO % m["id"], json={}).status_code == 200
    _refused(casey, bd_db, m["id"], 409, "This merge is already undone.")


def test_undo_of_an_older_merge_is_refused_once_the_account_is_merged_again(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    first = merged(casey, 12, 13)
    assert casey.post(UNDO % first["id"], json={}).status_code == 200
    merged(casey, 12, 13, name_from=13)
    _refused(casey, bd_db, first["id"], 409, "This merge is already undone.")
    assert company_row(bd_db, 12)["merged_into"] == 13


def test_undo_is_refused_when_a_moved_person_has_moved_company_since(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    m = merged(casey, 10, 11, name_from=11)
    r = casey.patch("/api/bd/contacts/21", json={"company": {"id": 16}})
    assert r.status_code == 200, r.text
    _refused(casey, bd_db, m["id"], 409, CHANGED)


def test_undo_is_refused_when_the_survivor_was_merged_on_with_the_people(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    m = merged(casey, 10, 11, name_from=11)
    third = company(bd_db, "Prairie Ridge Builders Co")
    merged(casey, 11, third, name_from=third)
    _refused(casey, bd_db, m["id"], 409, CHANGED)


def test_undo_is_refused_when_the_survivor_was_renamed_after_the_merge_renamed_it(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    m = merged(casey, 10, 11, name_from=10)
    assert casey.patch("/api/bd/companies/11", json={"name": "Prairie Ridge Group"}).status_code == 200
    _refused(casey, bd_db, m["id"], 409, CHANGED)


def test_a_rename_after_a_merge_that_kept_the_name_does_not_block_undo(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    m = merged(casey, 10, 11, name_from=11)
    assert casey.patch("/api/bd/companies/11", json={"name": "Prairie Ridge Group"}).status_code == 200
    assert casey.post(UNDO % m["id"], json={}).status_code == 200
    assert company_row(bd_db, 11)["name"] == "Prairie Ridge Group"             # the merge never set it


@pytest.mark.parametrize("merge_id", ["999999", "abc", "0"])
def test_undo_of_an_unknown_merge_is_404(bd_seeded, bd_as_user, bd_db, merge_id):
    _refused(bd_as_user(CASEY), bd_db, merge_id, 404, "That merge does not exist.")


def test_undo_of_an_event_that_is_not_a_merge_is_404(bd_seeded, bd_as_user, bd_db):
    r = bd_as_user(AVERY).post("/api/bd/contacts/accounts/16/move", json={"to": "maintenance"})
    assert r.status_code == 200, r.text
    _refused(bd_as_user(CASEY), bd_db, r.json()["move"]["id"], 404, "That merge does not exist.")


# ── the recently merged list ────────────────────────────────────────────────────────────────────
def test_the_recent_merges_newest_first_at_most_ten(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    first = merged(casey, 12, 13, name_from=13)
    body = casey.get(DUPES).json()
    assert body["merges"] == [{"id": first["id"], "account": {"id": 12, "name": "Cottonwood & Sons Paving"},
                               "into": {"id": 13, "name": "Cottonwood Sons Paving Co."},
                               "name_before": "Cottonwood Sons Paving Co.", "people": 1, "people_count": 2,
                               "at": first["at"], "by": {"id": CASEY, "name": "Casey Moret"}}]
    assert body["merges"] == [first]                       # the POST answer and the list are one Merge
    ids = [first["id"]]
    for n in range(10):
        a, b = company(bd_db, "Made Up Pair %d" % n), company(bd_db, "Made Up Pair %d LLC" % n)
        ids.append(merged(bd_as_user(EMERY), a, b)["id"])
    shown = casey.get(DUPES).json()["merges"]
    assert [x["id"] for x in shown] == ids[::-1][:10]
    assert shown[0]["by"] == {"id": EMERY, "name": "Emery Stoll"}


def test_a_merge_whose_survivor_was_merged_on_leaves_the_recent_list(bd_seeded, bd_as_user, bd_db):
    """12 into 13, then 13 into a third account: the first can never be undone now (its people are not
    at 13), so Recently merged offers only the second, whose survivor holds all three people."""
    casey = bd_as_user(CASEY)
    first = merged(casey, 12, 13, name_from=13)
    third = company(bd_db, "Cottonwood Sons Paving LLC")
    second = merged(casey, 13, third, name_from=third)
    shown = casey.get(DUPES).json()["merges"]
    assert [(x["id"], x["account"]["id"], x["into"]["id"], x["people_count"]) for x in shown] == [
        (second["id"], 13, third, 2)]
    _refused(casey, bd_db, first["id"], 409, CHANGED)


# ── keep separate ───────────────────────────────────────────────────────────────────────────────
def test_keep_separate_records_the_pair_once_and_it_is_never_listed_again(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    r = casey.post(KEEP, json={"accounts": [11, 10]})
    assert r.status_code == 200, r.text
    kept = r.json()["kept"]
    assert {k: kept[k] for k in ("a", "b", "decided_by")} == {
        "a": {"id": 10, "name": "Prairie Ridge Builders LLC"}, "b": {"id": 11, "name": "Prairie Ridge Builders, Inc."},
        "decided_by": {"id": CASEY, "name": "Casey Moret"}}
    rows = bd_db.execute("select account_a, account_b, decided_by from bd.account_pairs_kept").fetchall()
    assert rows == [{"account_a": 10, "account_b": 11, "decided_by": CASEY}]
    assert [(p["a"]["id"], p["b"]["id"]) for p in casey.get(DUPES).json()["items"]] == [(12, 13)]
    before = state(bd_db)
    again = bd_as_user(EMERY).post(KEEP, json={"accounts": [10, 11]})
    assert again.status_code == 200 and again.json()["kept"] == kept          # the first decision stands
    assert state(bd_db) == before


@pytest.mark.parametrize("body, status, message, fields", [
    ({"accounts": [10, 10]}, 400, "Some fields need fixing.", {"accounts": "Pick two different accounts."}),
    ({"accounts": [10]}, 400, "Some fields need fixing.", {"accounts": "Pick two different accounts."}),
    ({"accounts": [10, 11, 12]}, 400, "Some fields need fixing.", {"accounts": "Pick two different accounts."}),
    ({"accounts": ["10", 11]}, 400, "Some fields need fixing.", {"accounts": "Pick two different accounts."}),
    ({}, 400, "Some fields need fixing.", {"accounts": "Pick two different accounts."}),
    ([10, 11], 400, "Some fields need fixing.", {"body": "Send a JSON object."}),
    ({"accounts": [10, 999999]}, 404, "That company does not exist.", None),
])
def test_a_bad_keep_is_refused_and_changes_nothing(bd_seeded, bd_as_user, bd_db, body, status, message, fields):
    before = state(bd_db)
    r = bd_as_user(CASEY).post(KEEP, json=body)
    assert r.status_code == status, r.text
    assert r.json()["message"] == message and r.json().get("fields") == fields
    assert state(bd_db) == before


def test_a_merged_account_cannot_be_kept_separate(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    merge(casey, 12, 13)
    before = state(bd_db)
    r = casey.post(KEEP, json={"accounts": [12, 13]})
    assert (r.status_code, r.json()["message"]) == (409, "This account is already merged into another."), r.text
    assert state(bd_db) == before


# ── nothing merges on its own ───────────────────────────────────────────────────────────────────
def test_no_startup_hook_comes_from_the_merge_module():
    import main

    hooks = list(main.app.router.on_startup)
    assert hooks and all("account_merge" not in getattr(h, "__module__", "") for h in hooks)


def test_the_weekly_batch_and_every_read_leave_the_likely_pairs_unmerged(bd_seeded, bd_as_user, bd_db, monkeypatch):
    import datetime

    from bd import config as bd_config
    from bd import weekly_worker

    monkeypatch.setattr(bd_config, "BD_WEEKLY_ENABLED", True)
    friday = datetime.datetime.fromisoformat("2026-11-06T16:05:00-06:00")
    w = weekly_worker.Worker(interval=60, clock=lambda: friday)
    w.tick()
    assert w.failures == 0 and w.built, "the Friday batch did not run, so this proves nothing"
    for who in (AVERY, CASEY, DEVON, EMERY, FRANKIE):
        client = bd_as_user(who)
        for path in (DUPES, "/api/bd/contacts/accounts", "/api/bd/contacts/search?q=prairie", "/api/bd/companies",
                     "/api/bd/me"):
            assert client.get(path).status_code in (200, 403)
    marked = bd_db.execute("select count(*) as n from bd.companies where merged_into is not null").fetchone()["n"]
    events = bd_db.execute("select count(*) as n from bd.events where kind like 'company_merge%%'").fetchone()["n"]
    assert (marked, events) == (0, 0)
