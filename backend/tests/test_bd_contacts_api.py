"""One contact under /api/bd/ (#807): GET /api/bd/contacts/{id}, PATCH /api/bd/contacts/{id} and
POST /api/bd/contacts/{id}/confirm (bd/routers/contacts.py). This Week loads each task's contact
(its outcome and tray), the call dialog changes a contact after a touch, and "not the right person"
with no task confirms the contact.

Moved from BD's tests/test_contacts_api.py: its get-one, patch and confirm tests. The rest of that
file (the list, duplicates, create, archive) moves with the contact page (#808). BD ran these on its
mock seed; they now run on the fixture seed (bd/ops/fixture_seed.py, today Wed 2026-11-04) with the
expected answers worked out here. The contacts they lean on:
    Dana Whitlow (21)   Avery's, BD; live call Oct 20, voicemail Nov 2; task 302; recommendation 401
    Rory Sandell (22)   Blair's, BD, on the global (quarterly) cadence, never contacted; task 304
    Theo Banks (24)     Blair's; co-owner "Jules", a workbook name with no BD login
    Priya Nandan (25)   Avery's; a no-answer call Nov 3; Cedar Creek Concrete (14)
    Lena Ortiz (27)     Avery's; phone 913-555-0107
    Hal Brecken (30)    Avery's maintenance contact, 3 a year (the default)
    D. Whitlow (33)     Blair's; flagged as a possible duplicate of Dana ("Same email")
Everything is made up: example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import pytest

AVERY, BLAIR, CASEY, DEVON, EMERY, FRANKIE = 1, 2, 3, 4, 5, 6
ROLE_IDS = {"salesperson": BLAIR, "assistant": CASEY, "manager": DEVON, "admin": EMERY, "super_admin": FRANKIE}
BD_SENTENCE = "BD contacts follow the BD cadence. Set a follow-up override instead."
MANAGER_SENTENCE = "Managers can change only how often to follow up."
OVERRIDE = {"cadence_override": "monthly", "cadence_override_until": "2027-01-31"}


def is_envelope(body, code):
    return (isinstance(body, dict) and body.get("ok") is False and body.get("error") == code
            and isinstance(body.get("message"), str) and body["message"].strip()
            and body["message"][-1] in ".?!")


def events(db, contact_id, kind=None):
    sql = "select kind, actor_id, detail, data from bd.events where contact_id = %s"
    params = [contact_id]
    if kind:
        sql += " and kind = %s"
        params.append(kind)
    return db.execute(sql + " order by id", params).fetchall()


def contact_row(db, cid):
    return db.execute("select * from bd.contacts where id = %s", (cid,)).fetchone()


def set_setting(db, key, json_text):
    db.execute("insert into bd.settings (key, value) values (%s, %s::jsonb)"
               " on conflict (key) do update set value = excluded.value", (key, json_text))


# ── GET /api/bd/contacts/{id} ─────────────────────────────────────────────────────────────────
def test_danas_page(bd_seeded, bd_as_user):
    """Dana's cards: this week's task (302), the pending suggestion (401), and the missed-call card
    for her Nov 2 voicemail (16:00 UTC = 10:00 CST): after her last live talk (Oct 20), 2 days old,
    no follow-up sent."""
    r = bd_as_user(DEVON).get("/api/bd/contacts/21")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"ok", "contact", "open_task", "pending_recommendation", "missed_call"}
    c = body["contact"]
    assert (c["id"], c["name"], c["company"], c["owner"]) == (
        21, "Dana Whitlow", {"id": 10, "name": "Prairie Ridge Builders LLC"}, {"id": AVERY, "name": "Avery Quill"})
    # BD, quarterly: Oct 20 + 91 days = Jan 19; one touch of 4.
    assert (c["frequency_per_year"], c["cadence"], c["cadence_source"]) == (4, "quarterly", "global")
    assert (c["last_live_at"], c["next_due_date"], c["cadence_status"], c["touches_this_year"]) == (
        "2026-10-20T10:00:00-05:00", "2027-01-19", "on_track", 1)
    assert (c["last_attempt_at"], c["attempts_since_live"]) == ("2026-11-02T10:00:00-06:00", 1)
    assert body["open_task"]["id"] == 302 and body["open_task"]["contact"]["id"] == 21
    assert body["open_task"]["kind"] == "followup" and body["open_task"]["status"] == "open"
    rec = body["pending_recommendation"]
    assert (rec["id"], rec["action"], rec["due_date"], rec["status"]) == (
        401, "Send the spring schedule", "2026-11-06", "pending")
    assert body["missed_call"] == {"interaction_id": 102, "occurred_at": "2026-11-02T10:00:00-06:00",
                                   "followup_sent": False}


def test_a_contact_with_nothing_pending(bd_seeded, bd_as_user):
    body = bd_as_user(AVERY).get("/api/bd/contacts/27").json()
    assert (body["open_task"], body["pending_recommendation"], body["missed_call"]) == (None, None, None)
    # Lena is on a monthly override until Dec 31: 12 a year.
    c = body["contact"]
    assert (c["frequency_per_year"], c["cadence"], c["cadence_source"]) == (12, "monthly", "override")


@pytest.mark.parametrize("who", list(ROLE_IDS.values()) + [AVERY])
def test_every_role_reads_a_contact(bd_seeded, bd_as_user, who):
    assert bd_as_user(who).get("/api/bd/contacts/21").status_code == 200


@pytest.mark.parametrize("path", ["/api/bd/contacts/999", "/api/bd/contacts/0", "/api/bd/contacts/-3",
                                  "/api/bd/contacts/99999999999999999999", "/api/bd/contacts/abc"])
def test_ids_that_name_no_contact_are_404(bd_seeded, bd_as_user, path):
    r = bd_as_user(AVERY).get(path)
    assert r.status_code == 404 and r.json() == {"ok": False, "error": "not_found",
                                                 "message": "That contact does not exist."}


def test_the_one_contact_routes_need_a_sign_in(bd_seeded, bd_client):
    for method, path in (("GET", "/api/bd/contacts/21"), ("PATCH", "/api/bd/contacts/21"),
                         ("POST", "/api/bd/contacts/21/confirm")):
        assert bd_client.request(method, path).status_code == 401, (method, path)


def test_the_missed_call_card_lasts_14_central_days(bd_seeded, bd_as_user, bd_today):
    avery = bd_as_user(AVERY)
    bd_today("2026-11-16")                    # Nov 2 + 14
    assert avery.get("/api/bd/contacts/21").json()["missed_call"]["interaction_id"] == 102
    bd_today("2026-11-17")
    assert avery.get("/api/bd/contacts/21").json()["missed_call"] is None


def test_the_missed_call_age_is_counted_in_central_days(bd_seeded, bd_as_user, bd_db):
    """Marisa (23) has no calls. 01:00 UTC on Oct 21 is 20:00 CDT on Oct 20: 15 Central days before
    Nov 4, no card. 05:00 UTC is 00:00 CDT on Oct 21: 14 days, a card."""
    bd_db.execute("insert into bd.interactions (contact_id, kind, direction, outcome, occurred_at, provider)"
                  " values (23, 'call', 'out', 'no_answer', '2026-10-21T01:00:00Z', 'manual')")
    assert bd_as_user(AVERY).get("/api/bd/contacts/23").json()["missed_call"] is None
    bd_db.execute("update bd.interactions set occurred_at = '2026-10-21T05:00:00Z'"
                  " where contact_id = 23 and kind = 'call'")
    card = bd_as_user(AVERY).get("/api/bd/contacts/23").json()["missed_call"]
    assert card and card["occurred_at"] == "2026-10-21T00:00:00-05:00"


def test_no_card_after_a_followup_or_a_live_talk(bd_seeded, bd_as_user, bd_db):
    avery = bd_as_user(AVERY)
    bd_db.execute("update bd.interactions set followup_status = 'none' where id = 102")
    assert avery.get("/api/bd/contacts/21").json()["missed_call"] is None
    bd_db.execute("update bd.interactions set followup_status = null where id = 102")
    bd_db.execute("insert into bd.interactions (contact_id, kind, direction, outcome, occurred_at, provider)"
                  " values (21, 'call', 'out', 'answered', '2026-11-03T15:00:00Z', 'manual')")
    assert avery.get("/api/bd/contacts/21").json()["missed_call"] is None


def test_open_task_is_this_central_weeks_only(bd_seeded, bd_as_user, bd_today):
    blair = bd_as_user(BLAIR)
    assert blair.get("/api/bd/contacts/22").json()["open_task"]["id"] == 304
    bd_today("2026-11-08")                       # Sunday: still the week of Nov 2
    assert blair.get("/api/bd/contacts/22").json()["open_task"]["id"] == 304
    bd_today("2026-11-09")                       # Monday: a new week, no list yet
    assert blair.get("/api/bd/contacts/22").json()["open_task"] is None


def test_open_task_shows_a_done_task_too(bd_seeded, bd_as_user):
    """This week's task in any state (the call dialog's "done" tick reads it)."""
    t = bd_as_user(AVERY).get("/api/bd/contacts/25").json()["open_task"]
    assert (t["id"], t["status"], t["done_at"]) == (303, "done", "2026-11-03T12:00:00-06:00")


# ── PATCH /api/bd/contacts/{id} ──────────────────────────────────────────────────────────────
def test_an_override_on_dana_moves_her_due_date(bd_seeded, bd_as_user):
    """Monthly is 12 a year, an interval of 365 // 12 = 30 days: Oct 20 + 30 = Nov 19."""
    r = bd_as_user(AVERY).patch("/api/bd/contacts/21", json=OVERRIDE)
    assert r.status_code == 200, r.text
    c = r.json()["contact"]
    assert (c["frequency_per_year"], c["cadence"], c["cadence_source"]) == (12, "monthly", "override")
    assert (c["cadence_override"], c["cadence_override_until"]) == ("monthly", "2027-01-31")
    assert (c["next_due_date"], c["cadence_status"]) == ("2026-11-19", "on_track")
    assert r.json()["possible_duplicates"] == []


def test_changing_the_outcome_fields_after_a_call_saves(bd_seeded, bd_as_user, bd_db):
    """What the call dialog sends after a touch: the next step, its date and the promise."""
    body = {"next_step": "Send the sample board", "next_step_date": "2026-11-12", "promised_date": "2026-11-10",
            "stage": "Bidding"}
    c = bd_as_user(BLAIR).patch("/api/bd/contacts/22", json=body).json()["contact"]
    assert (c["next_step"], c["next_step_date"], c["promised_date"], c["stage"]) == (
        "Send the sample board", "2026-11-12", "2026-11-10", "Bidding")
    row = contact_row(bd_db, 22)
    assert (row["next_step"], str(row["next_step_date"]), str(row["promised_date"])) == (
        "Send the sample board", "2026-11-12", "2026-11-10")


@pytest.mark.parametrize("role,body,status", [
    ("salesperson", {"title": "A"}, 200), ("assistant", {"title": "A"}, 200), ("admin", {"title": "A"}, 200),
    ("super_admin", {"title": "A"}, 200), ("manager", {"title": "A"}, 403),
    ("manager", OVERRIDE, 200), ("assistant", OVERRIDE, 200), ("salesperson", OVERRIDE, 200),
    ("admin", OVERRIDE, 200), ("super_admin", OVERRIDE, 200),
    ("manager", {"cadence_override": None}, 200),
    ("manager", dict(OVERRIDE, importance=2), 403), ("manager", {"category": "maintenance"}, 403),
    ("manager", {"frequency_per_year": 3, "importance": 2}, 403),
    ("manager", {"frequency_per_year": 3}, 400), ("assistant", {"frequency_per_year": 3}, 400),
    ("salesperson", {"frequency_per_year": 3}, 400), ("admin", {"frequency_per_year": 3}, 400),
    ("salesperson", {"duplicate_of": None}, 403), ("assistant", {"duplicate_of": None}, 200),
    ("admin", {"duplicate_of": None}, 200), ("manager", {"duplicate_of": None}, 403),
])
def test_patch_roles(bd_seeded, bd_as_user, role, body, status):
    r = bd_as_user(ROLE_IDS[role]).patch("/api/bd/contacts/33", json=body)
    assert r.status_code == status, r.text
    if status == 403:
        assert is_envelope(r.json(), "forbidden")
    if status == 400:
        assert r.json()["fields"] == {"frequency_per_year": BD_SENTENCE}


def test_a_manager_who_may_not_edit_is_told_how_often_only(bd_seeded, bd_as_user):
    for body in ({"title": "A"}, dict(OVERRIDE, notes="x"), {"owner_id": 1}, {"category": "bd"}):
        r = bd_as_user(DEVON).patch("/api/bd/contacts/33", json=body)
        assert r.status_code == 403 and r.json()["message"] == MANAGER_SENTENCE, body


def test_a_manager_changes_a_maintenance_frequency_and_the_override_only(bd_seeded, bd_as_user):
    r = bd_as_user(DEVON).patch("/api/bd/contacts/30", json={"frequency_per_year": 5})
    assert r.status_code == 200 and r.json()["contact"]["frequency_per_year"] == 5
    assert r.json()["contact"]["cadence"] is None
    # An override on a maintenance contact is stored but means nothing (maintenance has no cadence).
    r = bd_as_user(DEVON).patch("/api/bd/contacts/30", json=OVERRIDE)
    assert r.status_code == 200
    c = r.json()["contact"]
    assert (c["cadence"], c["cadence_source"], c["frequency_per_year"]) == (None, None, 5)
    assert (c["cadence_override"], c["cadence_override_until"]) == ("monthly", "2027-01-31")


def test_a_refused_patch_changes_nothing(bd_seeded, bd_as_user, bd_db):
    before = contact_row(bd_db, 33)
    bd_as_user(DEVON).patch("/api/bd/contacts/33", json={"frequency_per_year": 9, "title": "X"})
    bd_as_user(BLAIR).patch("/api/bd/contacts/33", json={"title": "Y", "duplicate_of": None})
    bd_as_user(BLAIR).patch("/api/bd/contacts/33", json={"title": "Z", "owner_id": 99})
    bd_as_user(BLAIR).patch("/api/bd/contacts/33", json={"company": {"name": "Brand New Co"}, "owner_id": 99})
    assert contact_row(bd_db, 33) == before
    assert bd_db.execute("select count(*) as n from bd.companies where name = 'Brand New Co'").fetchone()["n"] == 0
    assert events(bd_db, 33) == []


def test_a_workbook_co_owner_survives_every_other_save(bd_seeded, bd_as_user, bd_db):
    """Jules has no BD login, so Theo's co_owner is {"id": null, "name": "Jules"}."""
    blair = bd_as_user(BLAIR)
    for body in ({"title": "Owner's Rep"}, {"owner_id": BLAIR}, OVERRIDE, {"notes": "x"},
                 {"company": {"name": "Another Cottonwood"}}):
        c = blair.patch("/api/bd/contacts/24", json=body).json()["contact"]
        assert c["co_owner"] == {"id": None, "name": "Jules"}, body
    bd_as_user(DEVON).patch("/api/bd/contacts/24", json={"cadence_override": "weekly",
                                                         "cadence_override_until": "2026-12-31"})
    assert blair.get("/api/bd/contacts/24").json()["contact"]["co_owner"] == {"id": None, "name": "Jules"}
    c = blair.patch("/api/bd/contacts/24", json={"co_owner_id": CASEY}).json()["contact"]
    assert c["co_owner"] == {"id": CASEY, "name": "Casey Moret"}
    c = blair.patch("/api/bd/contacts/24", json={"co_owner_id": None}).json()["contact"]
    assert c["co_owner"] is None
    assert bd_db.execute("select co_owner_id, co_owner_name from bd.contacts where id = 24").fetchone() == \
        {"co_owner_id": None, "co_owner_name": None}


def test_patch_logs_frequency_and_owner_changes(bd_seeded, bd_as_user, bd_db):
    bd_as_user(DEVON).patch("/api/bd/contacts/30", json={"frequency_per_year": 6})
    bd_as_user(DEVON).patch("/api/bd/contacts/30", json={"frequency_per_year": 6})      # no change, no event
    bd_as_user(CASEY).patch("/api/bd/contacts/30", json={"owner_id": BLAIR})
    bd_as_user(CASEY).patch("/api/bd/contacts/30", json={"owner_id": BLAIR})           # no change, no event
    bd_as_user(CASEY).patch("/api/bd/contacts/30", json={"owner_id": None})
    got = [(e["kind"], e["actor_id"], e["detail"]) for e in events(bd_db, 30)]
    assert got == [("frequency_changed", DEVON, "3 a year to 6 a year"), ("owner_changed", CASEY, "Now Blair Fenn"),
                   ("owner_changed", CASEY, "Now nobody")]
    assert events(bd_db, 30)[0]["data"] == {"from": 3, "to": 6}


def test_a_new_owner_releases_the_old_owners_maintenance_task(bd_seeded, bd_as_user, bd_db):
    """Hal's open maintenance task 301 is on Avery's list. Moved to Blair, it is snoozed to the next
    Monday, so the pin sits on one list."""
    bd_as_user(CASEY).patch("/api/bd/contacts/30", json={"owner_id": BLAIR})
    t = bd_db.execute("select status, snoozed_until from bd.tasks where id = 301").fetchone()
    assert (t["status"], str(t["snoozed_until"])) == ("snoozed", "2026-11-09")
    assert bd_db.execute("select status from bd.tasks where id = 302").fetchone()["status"] == "open"


def test_the_override_is_logged_in_words_and_only_when_it_changes(bd_seeded, bd_as_user, bd_db):
    """Rory follows the global quarterly cadence. Jan 31 2027 is a Sunday."""
    def logged():
        return [(e["kind"], e["actor_id"], e["detail"]) for e in events(bd_db, 22)]

    bd_as_user(DEVON).patch("/api/bd/contacts/22", json=OVERRIDE)
    bd_as_user(DEVON).patch("/api/bd/contacts/22", json=OVERRIDE)                  # no change, no event
    assert logged() == [("frequency_changed", DEVON, "Every quarter to every month until Sun, Jan 31")]
    bd_as_user(BLAIR).patch("/api/bd/contacts/22", json={"cadence_override": "weekly"})
    bd_as_user(BLAIR).patch("/api/bd/contacts/22", json={"cadence_override": None})
    bd_as_user(BLAIR).patch("/api/bd/contacts/22", json={"cadence_override": None})  # nothing to clear
    assert logged() == [
        ("frequency_changed", DEVON, "Every quarter to every month until Sun, Jan 31"),
        ("frequency_changed", BLAIR, "Every month to every week until Sun, Jan 31"),
        ("frequency_changed", BLAIR, "Back to the BD cadence, every quarter"),
    ]
    assert events(bd_db, 22)[0]["data"] == {
        "from": {"cadence_override": None, "cadence_override_until": None},
        "to": {"cadence_override": "monthly", "cadence_override_until": "2027-01-31"}}


def test_back_to_the_bd_cadence_names_the_global_one(bd_seeded, bd_as_user, bd_db):
    set_setting(bd_db, "bd_cadence", '"weekly"')
    bd_as_user(BLAIR).patch("/api/bd/contacts/22", json=OVERRIDE)
    bd_as_user(BLAIR).patch("/api/bd/contacts/22", json={"cadence_override": None})
    assert [e["detail"] for e in events(bd_db, 22)] == ["Every week to every month until Sun, Jan 31",
                                                         "Back to the BD cadence, every week"]


def test_the_override_moves_the_contacts_number_and_clearing_restores_it(bd_seeded, bd_as_user):
    blair = bd_as_user(BLAIR)
    c = blair.patch("/api/bd/contacts/22", json=OVERRIDE).json()["contact"]
    assert (c["frequency_per_year"], c["cadence"], c["cadence_source"]) == (12, "monthly", "override")
    c = blair.patch("/api/bd/contacts/22", json={"cadence_override": None}).json()["contact"]
    assert (c["frequency_per_year"], c["cadence"], c["cadence_source"]) == (4, "quarterly", "global")
    assert (c["cadence_override"], c["cadence_override_until"]) == (None, None)


def test_a_sent_override_day_counts_through_its_last_day(bd_seeded, bd_as_user, bd_today):
    blair = bd_as_user(BLAIR)
    assert blair.patch("/api/bd/contacts/22", json={"cadence_override": "weekly",
                                                     "cadence_override_until": "2026-11-04"}).status_code == 200
    assert blair.get("/api/bd/contacts/22").json()["contact"]["cadence_source"] == "override"
    bd_today("2026-11-05")
    c = blair.get("/api/bd/contacts/22").json()["contact"]
    assert (c["cadence_source"], c["cadence"], c["frequency_per_year"]) == ("global", "quarterly", 4)
    assert (c["cadence_override"], c["cadence_override_until"]) == ("weekly", "2026-11-04")   # still shown
    r2 = blair.patch("/api/bd/contacts/22", json={"cadence_override": "monthly"})
    assert r2.status_code == 400 and r2.json()["fields"] == {"cadence_override_until": "Pick a day from today on."}


def test_a_refused_override_changes_nothing(bd_seeded, bd_as_user, bd_db):
    before = contact_row(bd_db, 22)
    for body in ({"cadence_override": "monthly"}, {"cadence_override_until": "2027-01-31"},
                 {"cadence_override": "daily", "cadence_override_until": "2027-01-31"},
                 {"cadence_override": "monthly", "cadence_override_until": "2026-11-03", "title": "Z"}):
        assert bd_as_user(BLAIR).patch("/api/bd/contacts/22", json=body).status_code == 400, body
    assert contact_row(bd_db, 22) == before
    assert events(bd_db, 22) == []


@pytest.mark.parametrize("body,fields", [
    ({"cadence_override": ""}, {"cadence_override": "Pick weekly, monthly or quarterly."}),
    ({"cadence_override": "", "cadence_override_until": ""},
     {"cadence_override": "Pick weekly, monthly or quarterly."}),
    ({"cadence_override": "weekly", "cadence_override_until": ""},
     {"cadence_override_until": "Use a date (YYYY-MM-DD)."}),
    ({"cadence_override": "weekly", "cadence_override_until": "2027-01-31 "},
     {"cadence_override_until": "Use a date (YYYY-MM-DD)."}),
    ({"cadence_override": "weekly", "cadence_override_until": " 2027-01-31"},
     {"cadence_override_until": "Use a date (YYYY-MM-DD)."}),
    ({"cadence_override": "weekly", "cadence_override_until": "2027-01-31\n"},
     {"cadence_override_until": "Use a date (YYYY-MM-DD)."}),
])
def test_an_empty_or_padded_override_is_refused_and_changes_nothing(bd_seeded, bd_as_user, bd_db, body, fields):
    """Only null clears an override; "" and a date with anything around it are 400s. Lena (27) has
    an active one."""
    before = contact_row(bd_db, 27)
    r = bd_as_user(AVERY).patch("/api/bd/contacts/27", json=body)
    assert r.status_code == 400 and r.json()["fields"] == fields, r.text
    assert contact_row(bd_db, 27) == before


def test_patch_flags_a_new_duplicate_once(bd_seeded, bd_as_user):
    blair = bd_as_user(BLAIR)
    body = blair.patch("/api/bd/contacts/22", json={"email": "priya@cedarcreek.example.com"}).json()
    assert body["contact"]["duplicate_of"] == {"contact_id": 25, "name": "Priya Nandan",
                                               "company": "Cedar Creek Concrete", "reason": "Same email"}
    assert [d["contact_id"] for d in body["possible_duplicates"]] == [25]
    # A later match never replaces the flag that is there.
    body = blair.patch("/api/bd/contacts/22", json={"phone": "913-555-0107"}).json()
    assert [d["contact_id"] for d in body["possible_duplicates"]] == [27]
    assert body["contact"]["duplicate_of"]["contact_id"] == 25
    # An unchanged email is not checked again.
    assert blair.patch("/api/bd/contacts/22", json={"email": "priya@cedarcreek.example.com"}).json()[
        "possible_duplicates"] == []


def test_clearing_a_duplicate_flag_logs_it(bd_seeded, bd_as_user, bd_db):
    body = bd_as_user(CASEY).patch("/api/bd/contacts/33", json={"duplicate_of": None}).json()
    assert body["contact"]["duplicate_of"] is None
    assert bd_db.execute("select duplicate_of, duplicate_reason from bd.contacts where id = 33").fetchone() == \
        {"duplicate_of": None, "duplicate_reason": None}
    assert [(e["kind"], e["actor_id"], e["detail"]) for e in events(bd_db, 33)] == \
        [("duplicate_cleared", CASEY, "Was flagged with Dana Whitlow")]
    assert bd_as_user(CASEY).patch("/api/bd/contacts/33", json={"duplicate_of": None}).status_code == 200
    assert len(events(bd_db, 33)) == 1


def test_moving_into_an_existing_company_flags_it(bd_seeded, bd_as_user, bd_db):
    """"cedar creek concrete" is Cedar Creek Concrete (14) by its cleaned name; Priya works there."""
    body = bd_as_user(CASEY).patch("/api/bd/contacts/22", json={"company": {"name": "cedar creek concrete"}}).json()
    assert body["contact"]["company"] == {"id": 14, "name": "Cedar Creek Concrete"}
    assert body["contact"]["duplicate_of"] == {"contact_id": 25, "name": "Priya Nandan",
                                               "company": "Cedar Creek Concrete", "reason": "Same company name"}
    assert bd_db.execute("select count(*) as n from bd.companies where normalized_name = 'cedar creek concrete'"
                         ).fetchone()["n"] == 1


@pytest.mark.parametrize("body,fields", [
    ({"name": ""}, {"name": "A contact needs a name."}),
    ({"name": None}, {"name": "A contact needs a name."}),
    ({"frequency_per_year": 6}, {"frequency_per_year": BD_SENTENCE}),
    ({"frequency_per_year": None}, {"frequency_per_year": BD_SENTENCE}),
    ({"frequency_per_year": 6, "category": "bd"}, {"frequency_per_year": BD_SENTENCE}),
    ({"cadence_override": "monthly"}, {"cadence_override_until": "Pick the last day of the override."}),
    ({"cadence_override_until": "2027-01-31"}, {"cadence_override": "Pick how often first."}),
    ({"cadence_override": "monthly", "cadence_override_until": None},
     {"cadence_override_until": "Pick the last day of the override."}),
    ({"cadence_override": "monthly", "cadence_override_until": "2026-11-03"},
     {"cadence_override_until": "Pick a day from today on."}),
    ({"cadence_override": None, "cadence_override_until": "2027-01-31"}, {"cadence_override": "Pick how often first."}),
    ({"cadence_override": "daily", "cadence_override_until": "2027-01-31"},
     {"cadence_override": "Pick weekly, monthly or quarterly."}),
    ({"cadence_override": "Monthly", "cadence_override_until": "2027-01-31"},
     {"cadence_override": "Pick weekly, monthly or quarterly."}),
    ({"cadence_override": 4, "cadence_override_until": "2027-01-31"},
     {"cadence_override": "Pick weekly, monthly or quarterly."}),
    ({"cadence_override": "monthly", "cadence_override_until": "31 Jan 2027"},
     {"cadence_override_until": "Use a date (YYYY-MM-DD)."}),
    ({"cadence_override": "monthly", "cadence_override_until": 20270131},
     {"cadence_override_until": "Use a date (YYYY-MM-DD)."}),
    ({"importance": 0}, {"importance": "Use 1, 2 or 3."}),
    ({"importance": 4}, {"importance": "Use 1, 2 or 3."}),
    ({"lead_source": None}, {"lead_source": "Pick a lead source."}),
    ({"lead_source": ""}, {"lead_source": "Pick a lead source."}),
    ({"title": 7}, {"title": "Use text."}),
    ({"title": "x" * 201}, {"title": "Keep this to 200 characters or fewer."}),
    ({"notes": "x" * 20001}, {"notes": "Keep this to 20000 characters or fewer."}),
    ({"promised_date": "2026-13-01"}, {"promised_date": "Use a date (YYYY-MM-DD)."}),
    ({"next_step_date": "2026-11-05T10:00:00"}, {"next_step_date": "Use a date (YYYY-MM-DD)."}),
    ({"tags": ["a", 1]}, {"tags": "Use a list of words."}),
    ({"tags": ["x" * 61]}, {"tags": "Use at most 50 tags of 60 characters or fewer."}),
    ({"owner_id": "1"}, {"owner_id": "Pick a user."}),
    ({"co_owner_id": 1.5}, {"co_owner_id": "Pick a user."}),
    ({"company": None}, {"company": "Pick or type a company."}),
    ({"company": {"name": " "}}, {"company": "Pick or type a company."}),
    ({"duplicate_of": {"contact_id": 1}}, {"duplicate_of": "Send null to clear the flag."}),
    ({"category": "BD"}, {"category": "Use bd or maintenance."}),
])
def test_patch_validation(bd_seeded, bd_as_user, bd_db, body, fields):
    before = contact_row(bd_db, 22)
    r = bd_as_user(FRANKIE).patch("/api/bd/contacts/22", json=body)
    assert r.status_code == 400, r.text
    assert r.json() == {"ok": False, "error": "bad_request", "message": "Some fields need fixing.", "fields": fields}
    assert contact_row(bd_db, 22) == before


@pytest.mark.parametrize("body", [{"frequency_per_year": "6"}, {"frequency_per_year": 6.5},
                                  {"frequency_per_year": True}, {"frequency_per_year": 0},
                                  {"frequency_per_year": 53}])
def test_patch_validates_a_maintenance_frequency(bd_seeded, bd_as_user, bd_db, body):
    r = bd_as_user(FRANKIE).patch("/api/bd/contacts/30", json=body)
    assert r.status_code == 400, r.text
    assert r.json() == {"ok": False, "error": "bad_request", "message": "Some fields need fixing.",
                        "fields": {"frequency_per_year": "Use a number from 1 to 52."}}
    assert contact_row(bd_db, 30)["frequency_per_year"] == 3


def test_patch_unknown_ids(bd_seeded, bd_as_user):
    r = bd_as_user(BLAIR).patch("/api/bd/contacts/999", json={"title": "x"})
    assert r.status_code == 404 and r.json()["message"] == "That contact does not exist."
    # 404 before the role check
    assert bd_as_user(DEVON).patch("/api/bd/contacts/999", json={"title": "x"}).status_code == 404
    r = bd_as_user(BLAIR).patch("/api/bd/contacts/22", json={"company": {"id": 999}})
    assert r.status_code == 404 and r.json()["message"] == "That company does not exist."
    r = bd_as_user(BLAIR).patch("/api/bd/contacts/22", json={"co_owner_id": 99})
    assert r.status_code == 400 and r.json()["fields"] == {"co_owner_id": "Pick a user."}


def test_patch_ignores_derived_fields(bd_seeded, bd_as_user):
    before = bd_as_user(BLAIR).get("/api/bd/contacts/22").json()["contact"]
    body = {"cadence_status": "complete", "touches_this_year": 40, "phone_e164": "+19999999999",
            "last_live_at": None, "source": "import", "archived_at": "2026-01-01T00:00:00-06:00"}
    after = bd_as_user(BLAIR).patch("/api/bd/contacts/22", json=body).json()["contact"]
    assert after == before


def test_patch_dates_and_clearing_notes(bd_seeded, bd_as_user):
    c = bd_as_user(AVERY).patch("/api/bd/contacts/21", json={"promised_date": "2026-11-30", "notes": None,
                                                             "tags": []}).json()["contact"]
    assert c["promised_date"] == "2026-11-30" and c["notes"] == "" and c["tags"] == []
    c = bd_as_user(AVERY).patch("/api/bd/contacts/21", json={"promised_date": ""}).json()["contact"]
    assert c["promised_date"] is None


def test_a_category_flip_without_a_number_takes_the_new_categorys_default(bd_seeded, bd_as_user, bd_db):
    """A BD contact's stored number is the cadence's (52 for weekly); flipped to maintenance it must
    not carry over as the maintenance target."""
    set_setting(bd_db, "bd_cadence", '"weekly"')
    set_setting(bd_db, "default_frequency", '{"maintenance": 2}')
    blair = bd_as_user(BLAIR)
    c = blair.patch("/api/bd/contacts/22", json={"category": "maintenance"}).json()["contact"]
    assert (c["frequency_per_year"], c["cadence"]) == (2, None)
    assert contact_row(bd_db, 22)["frequency_per_year"] == 2
    blair.patch("/api/bd/contacts/22", json={"frequency_per_year": 5})
    c = blair.patch("/api/bd/contacts/22", json={"category": "bd"}).json()["contact"]
    assert (c["frequency_per_year"], c["cadence"]) == (52, "weekly")
    assert contact_row(bd_db, 22)["frequency_per_year"] == 52
    c = blair.patch("/api/bd/contacts/22", json={"category": "maintenance", "frequency_per_year": 6}).json()["contact"]
    assert c["frequency_per_year"] == 6
    c = blair.patch("/api/bd/contacts/22", json={"category": "maintenance", "title": "T"}).json()["contact"]
    assert c["frequency_per_year"] == 6


# ── POST /api/bd/contacts/{id}/confirm ───────────────────────────────────────────────────────
def test_confirm_answers_and_logs_changes(bd_seeded, bd_as_user, bd_db):
    """Rory starts unconfirmed (the column's default)."""
    r = bd_as_user(BLAIR).post("/api/bd/contacts/22/confirm", json={"confirmed": True})
    assert r.status_code == 200 and r.json() == {"ok": True, "contact": {"id": 22, "confirmed": True}}
    bd_as_user(BLAIR).post("/api/bd/contacts/22/confirm", json={"confirmed": True})      # no change, no event
    bd_as_user(CASEY).post("/api/bd/contacts/22/confirm", json={"confirmed": False})
    bd_as_user(CASEY).post("/api/bd/contacts/22/confirm")                               # no body = confirm
    assert [(e["kind"], e["actor_id"]) for e in events(bd_db, 22)] == [
        ("confirmed", BLAIR), ("unconfirmed", CASEY), ("confirmed", CASEY)]
    assert contact_row(bd_db, 22)["confirmed"] is True


def test_not_the_right_person_with_no_task_unconfirms_the_contact(bd_seeded, bd_as_user, bd_db):
    """The call dialog's fallback when the contact has no task this week: confirmed false."""
    bd_as_user(AVERY).post("/api/bd/contacts/27/confirm", json={"confirmed": True})
    r = bd_as_user(AVERY).post("/api/bd/contacts/27/confirm", json={"confirmed": False})
    assert r.json() == {"ok": True, "contact": {"id": 27, "confirmed": False}}
    assert bd_as_user(AVERY).get("/api/bd/contacts/27").json()["contact"]["confirmed"] is False


@pytest.mark.parametrize("role,allowed", [("salesperson", True), ("assistant", True), ("manager", False),
                                          ("admin", True), ("super_admin", True)])
def test_confirm_roles(bd_seeded, bd_as_user, role, allowed):
    r = bd_as_user(ROLE_IDS[role]).post("/api/bd/contacts/22/confirm", json={"confirmed": True})
    assert r.status_code == (200 if allowed else 403)
    if not allowed:
        assert r.json() == {"ok": False, "error": "forbidden", "message": "Your role can't do that."}


def test_confirm_errors(bd_seeded, bd_as_user):
    r = bd_as_user(BLAIR).post("/api/bd/contacts/999/confirm", json={"confirmed": True})
    assert r.status_code == 404 and is_envelope(r.json(), "not_found")
    r = bd_as_user(BLAIR).post("/api/bd/contacts/22/confirm", json={"confirmed": "no"})
    assert r.status_code == 400 and r.json()["fields"] == {"confirmed": "Use true or false."}
