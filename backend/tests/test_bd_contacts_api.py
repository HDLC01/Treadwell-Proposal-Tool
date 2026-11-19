"""The contacts routes under /api/bd/ (bd/routers/contacts.py), moved from BD's tests/test_contacts_api.py.

#807 moved one contact: GET /api/bd/contacts/{id}, PATCH /api/bd/contacts/{id} and
POST /api/bd/contacts/{id}/confirm (This Week loads each task's contact, the call dialog changes a
contact after a touch, and "not the right person" with no task confirms the contact). #808 moves the
rest with the contact page and Add contact: the list (GET /api/bd/contacts), the possible-duplicate
person check (GET /api/bd/contacts/duplicates), create (POST /api/bd/contacts) and archive
(POST /api/bd/contacts/{id}/archive). Merge stays a later phase.

BD ran these on its mock seed and compared them with its mock API (both retired in #806); they now
run on the fixture seed (bd/ops/fixture_seed.py, today Wed 2026-11-04) with the expected answers
worked out here by hand. The contacts they lean on:
    Dana Whitlow (21)   Avery's, BD; live call Oct 20, voicemail Nov 2; task 302; recommendation 401
    Rory Sandell (22)   Blair's, BD, on the global (quarterly) cadence, never contacted; task 304
    Marisa Cole (23)    Avery's; a meeting Jun 15, so behind
    Theo Banks (24)     Blair's; co-owner "Jules", a workbook name with no BD login
    Priya Nandan (25)   Avery's; a no-answer call Nov 3; Cedar Creek Concrete (14); task 303 done
    Owen Pratt (26)     Blair's; the same phone as Priya, at Cedar Crest Concrete (15)
    Lena Ortiz (27)     Avery's; phone 913-555-0107
    Sam Achebe (28)     Blair's; task 305 skipped to Nov 10
    Hal Brecken (30)    Avery's maintenance contact, 3 a year (the default)
    Wes Calder (32)     nobody's, at Osage Plains Brewing (18)
    D. Whitlow (33)     Blair's; flagged as a possible duplicate of Dana ("Same email")
Everything is made up: example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import urllib.parse

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


@pytest.mark.parametrize("method, path", [("PATCH", "/api/bd/contacts/21"), ("POST", "/api/bd/contacts/21/confirm")])
@pytest.mark.parametrize("body", [["next_step"], "Call back", 7])
def test_a_body_that_is_not_an_object_is_400_in_one_sentence(bd_seeded, bd_as_user, bd_db, method, path, body):
    """The same words every BD route uses for a body that is not a JSON object (bd/paging.py)."""
    r = bd_as_user(AVERY).request(method, path, json=body)
    assert r.status_code == 400 and r.json() == {"ok": False, "error": "bad_request",
                                                 "message": "Some fields need fixing.",
                                                 "fields": {"body": "Send a JSON object."}}, r.text
    c = bd_db.execute("select confirmed, next_step from bd.contacts where id = 21").fetchone()
    assert (c["confirmed"], c["next_step"]) == (True, "Send the epoxy sample board")


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


# ── GET /api/bd/contacts (#808) ───────────────────────────────────────────────────────────────
# The default order is the company name (lower case, compared byte by byte as JavaScript compares
# strings), then the person's name, then the id. Worked by hand from the fixture seed:
#   bluestem logistics            Ines Varga 29, Lena Ortiz 27, Sam Achebe 28
#   cedar creek concrete          Priya Nandan 25
#   cedar crest concrete          Owen Pratt 26
#   cottonwood & sons paving      Marisa Cole 23          ("&" sorts before "s")
#   cottonwood sons paving co.    Theo Banks 24
#   kaw valley cold storage       Hal Brecken 30, Nora Lindqvist 31
#   osage plains brewing          Wes Calder 32
#   prairie ridge builders llc    Dana Whitlow 21         (a space sorts before ",")
#   prairie ridge builders, inc.  D. Whitlow 33, Rory Sandell 22   ("." sorts before "a")
BY_COMPANY = [29, 27, 28, 25, 26, 23, 24, 30, 31, 32, 21, 33, 22]
BY_NAME = [33, 21, 30, 29, 27, 23, 31, 26, 25, 22, 28, 24, 32]


def ids(body):
    return [c["id"] for c in body["items"]]


def test_the_list_in_company_order(bd_seeded, bd_as_user):
    body = bd_as_user(DEVON).get("/api/bd/contacts").json()
    assert set(body) == {"ok", "total", "items"} and body["ok"] is True
    assert (body["total"], ids(body)) == (13, BY_COMPANY)
    # Each item is the full Contact, the same object the contact's own page gets.
    dana = next(c for c in body["items"] if c["id"] == 21)
    assert dana == bd_as_user(DEVON).get("/api/bd/contacts/21").json()["contact"]


@pytest.mark.parametrize("query,want", [
    ("?sort=name", BY_NAME),
    ("?sort=company", BY_COMPANY),
    # Dana Oct 20, Hal Aug 20, Marisa Jun 15; nobody else has talked live (ties by id).
    ("?sort=last_live_at", [21, 30, 23, 22, 24, 25, 26, 27, 28, 29, 31, 32, 33]),
    # Due: Marisa Jun 15 + 91 = Sep 14; Hal Aug 20 + 120 = Dec 18; Dana Oct 20 + 91 = Jan 19.
    ("?sort=next_due_date", [23, 30, 21, 22, 24, 25, 26, 27, 28, 29, 31, 32, 33]),
    ("?category=maintenance", [30, 31]),
    ("?category=bd", [29, 27, 28, 25, 26, 23, 24, 32, 21, 33, 22]),
    ("?owner=1", [27, 25, 23, 30, 31, 21]),
    ("?owner=2", [28, 26, 24, 33, 22]),
    ("?company=16", [29, 27, 28]),
    ("?duplicates=true", [33]),
    ("?duplicates=false", BY_COMPANY),
    ("?confirmed=true", [21]),
    ("?industry=General%20contractor", [21]),
    ("?lead_source=Referral", [21]),
    ("?stage=Bidding", [21]),
    ("?cadence=behind", [23]),
    ("?cadence=on_track", [30, 21]),
    ("?cadence=complete", []),
    ("?cadence=never", [29, 27, 28, 25, 26, 24, 31, 32, 33, 22]),
    ("?archived=true", []),
    ("?q=whitlow", [21, 33]),
    ("?q=BLUESTEM", [29, 27, 28]),
    ("?q=estimator", [26, 22]),
    ("?q=lenexa", []),                      # a company's city is not a contact's
    ("?q=overland%20park", [21]),           # Dana's own city
    ("?q=prairie%20ridge%20builders%20inc", [21, 33, 22]),   # both accounts, by the cleaned name
    ("?q=0105", [25, 26]),                  # 785-555-0105 and +1 785 555 0105
    ("?q=(785)%20555-0105", [25, 26]),
    ("?q=55", []),                          # two digits are not a phone search
    ("?q=%20%20", BY_COMPANY),
    ("?q=nobody-by-this-name", []),
    ("?category=bd&owner=1&sort=name", [21, 27, 23, 25]),
])
def test_the_list_filters_sorts_and_searches(bd_seeded, bd_as_user, query, want):
    body = bd_as_user(AVERY).get("/api/bd/contacts" + query).json()
    assert ids(body) == want, (query, ids(body))
    assert body["total"] == len(want)


def test_the_list_pages_and_the_total_counts_every_match(bd_seeded, bd_as_user):
    c = bd_as_user(BLAIR)
    body = c.get("/api/bd/contacts?limit=5&offset=5").json()
    assert (body["total"], ids(body)) == (13, BY_COMPANY[5:10])
    assert ids(c.get("/api/bd/contacts?limit=0").json()) == BY_COMPANY          # 0 is the default
    assert ids(c.get("/api/bd/contacts?limit=900").json()) == BY_COMPANY        # past the cap of 500
    assert c.get("/api/bd/contacts?offset=1000").json() == {"ok": True, "total": 13, "items": []}


def test_an_archived_contact_is_left_out_unless_asked_for(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("update bd.contacts set archived_at = '2026-11-03T15:00:00Z' where id = 28")
    c = bd_as_user(DEVON)
    assert 28 not in ids(c.get("/api/bd/contacts").json())
    body = c.get("/api/bd/contacts?archived=true").json()
    assert (body["total"], ids(body)) == (1, [28])
    assert body["items"][0]["archived_at"] == "2026-11-03T09:00:00-06:00"
    assert "archived_at" not in c.get("/api/bd/contacts?limit=1").json()["items"][0]


def test_the_search_is_text_not_a_pattern(bd_seeded, bd_as_user):
    c = bd_as_user(AVERY)
    for q in ("zz%25zz", "d_na", urllib.parse.quote("'; drop table contacts; --")):
        assert c.get("/api/bd/contacts?q=" + q).json()["total"] == 0, q
    assert c.get("/api/bd/contacts").json()["total"] == 13


@pytest.mark.parametrize("query,fields", [
    ("sort=priority", {"sort": "Use name, company, last_live_at or next_due_date."}),
    ("category=retail", {"category": "Use bd or maintenance."}),
    ("cadence=late", {"cadence": "Use never, behind, on_track or complete."}),
    ("confirmed=yes", {"confirmed": "Use true or false."}),
    ("duplicates=1", {"duplicates": "Use true or false."}),
    ("archived=maybe", {"archived": "Use true or false."}),
    ("owner=avery", {"owner": "Use a whole number."}),
    ("company=abc", {"company": "Use a whole number."}),
    ("limit=ten", {"limit": "Use a whole number."}),
    ("limit=-1", {"limit": "Use a whole number from 0."}),
    ("offset=-5", {"offset": "Use a whole number from 0."}),
])
def test_a_bad_list_query_is_400_with_the_field(bd_seeded, bd_as_user, query, fields):
    r = bd_as_user(AVERY).get("/api/bd/contacts?" + query)
    message = "Unknown sort." if "sort" in fields else "Some fields need fixing."
    assert r.status_code == 400 and r.json() == {"ok": False, "error": "bad_request", "message": message,
                                                 "fields": fields}, r.text


def test_the_list_follows_the_central_today(bd_seeded, bd_as_user, bd_today):
    """On Jan 20 Dana's Jan 19 is past, and Hal's Dec 18 too."""
    c = bd_as_user(DEVON)
    assert ids(c.get("/api/bd/contacts?cadence=behind").json()) == [23]
    bd_today("2027-01-20")
    assert ids(c.get("/api/bd/contacts?cadence=behind").json()) == [23, 30, 21]


# ── GET /api/bd/contacts/duplicates (#808): the possible-duplicate-person check ─────────────────
def dup(cid, name, company, city, reason):
    return {"contact_id": cid, "name": name, "company": company, "city": city, "reason": reason}


DANA = ("Dana Whitlow", "Prairie Ridge Builders LLC", "Overland Park")
RORY = ("Rory Sandell", "Prairie Ridge Builders, Inc.", None)
D_WHITLOW = ("D. Whitlow", "Prairie Ridge Builders, Inc.", None)
PRIYA = ("Priya Nandan", "Cedar Creek Concrete", None)
OWEN = ("Owen Pratt", "Cedar Crest Concrete", None)


@pytest.mark.parametrize("query,want", [
    # "Prairie Ridge Builders" is the cleaned name of both accounts 10 and 11.
    ("?company=Prairie%20Ridge%20Builders", [dup(21, *DANA, "Same company name"), dup(22, *RORY, "Same company name"),
                                             dup(33, *D_WHITLOW, "Same company name")]),
    ("?company=prairie%20ridge%20builders,%20inc.&except=33",
     [dup(21, *DANA, "Same company name"), dup(22, *RORY, "Same company name")]),
    ("?email=%20DANA.WHITLOW@prairieridge.example.com", [dup(21, *DANA, "Same email"), dup(33, *D_WHITLOW, "Same email")]),
    ("?phone=(785)%20555-0105", [dup(25, *PRIYA, "Same phone"), dup(26, *OWEN, "Same phone")]),
    ("?phone=17855550105", [dup(25, *PRIYA, "Same phone"), dup(26, *OWEN, "Same phone")]),
    # Each person once, with the first reason that matches them.
    ("?company=Cedar%20Creek%20Concrete&phone=785.555.0105",
     [dup(25, *PRIYA, "Same company name"), dup(26, *OWEN, "Same phone")]),
    ("?phone=913-555-0107&except=27", []),
    ("?company=Juniper%20Hollow%20Dental", []),
    ("", []),
])
def test_the_duplicate_check(bd_seeded, bd_as_user, query, want):
    r = bd_as_user(CASEY).get("/api/bd/contacts/duplicates" + query)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True, "items": want}


def test_an_archived_person_is_no_duplicate(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("update bd.contacts set archived_at = bd_now() where id = 25")
    items = bd_as_user(AVERY).get("/api/bd/contacts/duplicates?phone=785-555-0105").json()["items"]
    assert [i["contact_id"] for i in items] == [26]


def test_except_must_be_a_number(bd_seeded, bd_as_user):
    r = bd_as_user(AVERY).get("/api/bd/contacts/duplicates?company=x&except=abc")
    assert r.status_code == 400 and r.json()["fields"] == {"except": "Use a whole number."}


def test_duplicates_is_never_read_as_a_contact_id(bd_seeded, bd_as_user):
    assert bd_as_user(AVERY).get("/api/bd/contacts/duplicates").json() == {"ok": True, "items": []}


# ── POST /api/bd/contacts (#808): Add contact ─────────────────────────────────────────────────
ARI = {"company": {"name": "  Juniper Hollow  Dental "}, "name": " Ari Mendel ", "title": "Office Manager",
       "email": " ari@juniperhollow.example.com", "phone": "913.555.0113", "lead_source": "Referral",
       "notes": "Met at the dental expo."}


def count(bd_db, table):
    return bd_db.execute("select count(*) as n from bd." + table).fetchone()["n"]


def test_a_new_contact_at_a_new_company(bd_seeded, bd_as_user, bd_db):
    """The fixture's ids end at company 18 and contact 33, so these are 19 and 34."""
    r = bd_as_user(BLAIR).post("/api/bd/contacts", json=ARI)
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body) == {"ok", "contact", "possible_duplicates"} and body["possible_duplicates"] == []
    c = body["contact"]
    assert set(c) == set(bd_as_user(BLAIR).get("/api/bd/contacts/22").json()["contact"])
    assert (c["id"], c["company"], c["name"], c["title"]) == (
        34, {"id": 19, "name": "Juniper Hollow Dental"}, "Ari Mendel", "Office Manager")
    assert (c["email"], c["phone"], c["phone_e164"]) == ("ari@juniperhollow.example.com", "913.555.0113", "+19135550113")
    # A salesperson's new contact is theirs; BD follows the global cadence (quarterly: 4 a year).
    assert (c["owner"], c["co_owner"], c["category"]) == ({"id": BLAIR, "name": "Blair Fenn"}, None, "bd")
    assert (c["frequency_per_year"], c["cadence"], c["cadence_source"], c["cadence_status"]) == (
        4, "quarterly", "global", "never")
    assert (c["confirmed"], c["importance"], c["source"], c["lead_source"], c["notes"]) == (
        False, 1, "manual", "Referral", "Met at the dental expo.")
    assert (c["duplicate_of"], c["tags"], c["last_live_at"], c["maintenance_due"]) == (None, [], None, False)
    assert c["created_at"].startswith("2026-11-04T") and c["created_at"].endswith("-06:00")
    row = bd_db.execute("select name, normalized_name from bd.companies where id = 19").fetchone()
    assert row == {"name": "Juniper Hollow Dental", "normalized_name": "juniper hollow dental"}
    assert [(e["kind"], e["actor_id"], e["detail"]) for e in events(bd_db, 34)] == [("created", BLAIR, "Added by hand")]
    assert events(bd_db, 34)[0]["data"] == {"source": "manual", "company_id": 19}


def test_a_new_contact_at_an_existing_account_is_flagged(bd_seeded, bd_as_user, bd_db):
    """"PRAIRIE RIDGE BUILDERS INC" cleans to the name of accounts 10 and 11: it lands on the first
    (10), and everyone at either is a possible duplicate; the flag is the first of them, Dana."""
    r = bd_as_user(AVERY).post("/api/bd/contacts", json={"company": {"name": "PRAIRIE RIDGE BUILDERS INC"},
                                                          "name": "Jo Ferris"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["contact"]["company"] == {"id": 10, "name": "Prairie Ridge Builders LLC"}
    assert body["contact"]["duplicate_of"] == {"contact_id": 21, "name": "Dana Whitlow",
                                               "company": "Prairie Ridge Builders LLC", "reason": "Same company name"}
    assert [(d["contact_id"], d["reason"]) for d in body["possible_duplicates"]] == [
        (21, "Same company name"), (22, "Same company name"), (33, "Same company name")]
    assert count(bd_db, "companies") == 9
    # The contact list's duplicates filter shows the new one (account 10) before D. Whitlow (11).
    assert ids(bd_as_user(AVERY).get("/api/bd/contacts?duplicates=true").json()) == [34, 33]


def test_a_new_contact_picked_by_company_id(bd_seeded, bd_as_user):
    body = bd_as_user(CASEY).post("/api/bd/contacts", json={"company": {"id": 18}, "name": "Ruth Okafor"}).json()
    assert body["contact"]["company"] == {"id": 18, "name": "Osage Plains Brewing"}
    # The company's city and industry fill the contact's when it sends none.
    assert (body["contact"]["city"], body["contact"]["industry"]) == ("Manhattan", "Food and beverage")
    assert [(d["contact_id"], d["reason"]) for d in body["possible_duplicates"]] == [(32, "Same company name")]


def test_a_same_email_elsewhere_is_flagged(bd_seeded, bd_as_user):
    body = bd_as_user(BLAIR).post("/api/bd/contacts", json={"company": {"name": "Other Co"}, "name": "P. Nandan",
                                                            "email": "PRIYA@cedarcreek.example.com"}).json()
    assert body["possible_duplicates"] == [dup(25, *PRIYA, "Same email")]
    assert body["contact"]["duplicate_of"] == {"contact_id": 25, "name": "Priya Nandan",
                                               "company": "Cedar Creek Concrete", "reason": "Same email"}


def test_an_archived_contact_is_not_a_duplicate_of_a_new_one(bd_seeded, bd_as_user):
    bd_as_user(AVERY).post("/api/bd/contacts/25/archive", json={})
    body = bd_as_user(AVERY).post("/api/bd/contacts", json={"company": {"name": "Other Co"}, "name": "N",
                                                            "email": "priya@cedarcreek.example.com"}).json()
    assert body["possible_duplicates"] == [] and body["contact"]["duplicate_of"] is None


@pytest.mark.parametrize("who,owner", [(CASEY, {"id": AVERY, "name": "Avery Quill"}),
                                       (EMERY, {"id": AVERY, "name": "Avery Quill"}),
                                       (AVERY, {"id": AVERY, "name": "Avery Quill"}),
                                       (BLAIR, {"id": BLAIR, "name": "Blair Fenn"})])
def test_the_default_owner_is_me_else_the_first_salesperson(bd_seeded, bd_as_user, who, owner):
    c = bd_as_user(who).post("/api/bd/contacts", json={"company": {"name": "Q Co"}, "name": "Q One"}).json()["contact"]
    assert c["owner"] == owner


def test_a_new_contact_with_an_owner_and_a_co_owner(bd_seeded, bd_as_user):
    c = bd_as_user(CASEY).post("/api/bd/contacts", json={"company": {"name": "Pair Co"}, "name": "Two Owners",
                                                         "owner_id": BLAIR, "co_owner_id": AVERY}).json()["contact"]
    assert c["owner"] == {"id": BLAIR, "name": "Blair Fenn"} and c["co_owner"] == {"id": AVERY, "name": "Avery Quill"}


def test_a_client_never_sets_the_source_or_a_derived_field(bd_seeded, bd_as_user):
    body = {"company": {"name": "Sourcey"}, "name": "Q Person", "source": "proposal_tool",
            "cadence_status": "complete", "touches_this_year": 9, "phone_e164": "+19999999999",
            "phone": "816-555-0177", "id": 5, "archived_at": "2026-01-01T00:00:00-06:00"}
    c = bd_as_user(CASEY).post("/api/bd/contacts", json=body).json()["contact"]
    assert (c["id"], c["source"], c["cadence_status"], c["touches_this_year"]) == (34, "manual", "never", 0)
    assert c["phone_e164"] == "+18165550177" and "archived_at" not in c


def test_a_new_maintenance_contact_takes_the_default_or_its_number(bd_seeded, bd_as_user):
    """The default is settings.default_frequency.maintenance (3); a number is kept between 1 and 52,
    rounded half up; 0 or less, or null, takes the default."""
    c = bd_as_user(CASEY)

    def add(name, **extra):
        body = dict({"company": {"name": "Ironvale Power & Light, Inc."}, "name": name, "category": "maintenance",
                     "account_type": "Utility"}, **extra)
        return c.post("/api/bd/contacts", json=body).json()["contact"]

    ola = add("Ola Brandt", confirmed=True)
    assert (ola["frequency_per_year"], ola["cadence"], ola["cadence_source"]) == (3, None, None)
    assert (ola["confirmed"], ola["account_type"], ola["maintenance_due"], ola["maintenance_due_date"]) == (
        True, "Utility", True, None)
    assert [add(n, frequency_per_year=f)["frequency_per_year"] for n, f in
            (("A", 99), ("B", 0), ("C", 2.5), ("D", -4), ("E", None), ("F", 6))] == [52, 3, 3, 3, 3, 6]


@pytest.mark.parametrize("cadence,freq", [("weekly", 52), ("monthly", 12), ("quarterly", 4)])
def test_a_new_bd_contact_stores_its_cadences_number(bd_seeded, bd_as_user, bd_db, cadence, freq):
    set_setting(bd_db, "bd_cadence", '"%s"' % cadence)
    c = bd_as_user(BLAIR).post("/api/bd/contacts", json={"company": {"name": "G Co"}, "name": "G One"}).json()["contact"]
    assert (c["frequency_per_year"], c["cadence"]) == (freq, cadence)
    assert contact_row(bd_db, c["id"])["frequency_per_year"] == freq


def test_the_maintenance_default_comes_from_settings(bd_seeded, bd_as_user, bd_db):
    set_setting(bd_db, "default_frequency", '{"maintenance": 2}')
    c = bd_as_user(BLAIR).post("/api/bd/contacts", json={"company": {"name": "F Co"}, "name": "F Two",
                                                         "category": "maintenance"}).json()["contact"]
    assert c["frequency_per_year"] == 2


def test_a_bd_frequency_is_refused_whatever_it_is(bd_seeded, bd_as_user, bd_db):
    for extra in ({}, {"category": "bd"}):
        for freq in (4, 12, 52, 0, 99, "x", None):
            r = bd_as_user(BLAIR).post("/api/bd/contacts", json=dict({"company": {"name": "H Co"}, "name": "H One",
                                                                      "frequency_per_year": freq}, **extra))
            assert r.status_code == 400, freq
            assert r.json()["fields"] == {"frequency_per_year": BD_SENTENCE}
    assert bd_db.execute("select count(*) as n from bd.companies where name = 'H Co'").fetchone()["n"] == 0


@pytest.mark.parametrize("body,fields", [
    ({"company": {"name": "A"}, "name": "B", "importance": 5}, {"importance": "Use 1, 2 or 3."}),
    ({"company": {"name": "A"}, "name": "B", "tags": "x"}, {"tags": "Use a list of words."}),
    ({"company": {"name": "A"}, "name": "B", "next_step_date": "11/05/2026"},
     {"next_step_date": "Use a date (YYYY-MM-DD)."}),
    ({"company": {"name": "A"}, "name": "B", "last_quote_date": "soon"}, {"last_quote_date": "Use a date (YYYY-MM-DD)."}),
    ({"company": {"name": "A"}, "name": "B", "email": 5}, {"email": "Use text."}),
    ({"company": {"name": "A"}, "name": "B", "confirmed": "yes"}, {"confirmed": "Use true or false."}),
    ({"company": {"name": "A"}, "name": "B", "category": "maintenance", "frequency_per_year": "4"},
     {"frequency_per_year": "Use a number from 1 to 52."}),
    ({"company": {"name": "A"}, "name": "B", "category": "retail"}, {"category": "Use bd or maintenance."}),
    ({"company": {"name": "A"}, "name": "B", "owner_id": "avery"}, {"owner_id": "Pick a user."}),
    ({"company": {"name": "A"}, "name": "B", "co_owner_id": 1.5}, {"co_owner_id": "Pick a user."}),
    ({"company": "Acme", "name": "B"}, {"company": "Pick or type a company."}),
    ({"company": {"name": "c" * 201}, "name": "B"}, {"company": "Keep this to 200 characters or fewer."}),
    ({"company": {"name": "  "}, "name": "  "}, {"company": "Pick or type a company.",
                                                 "name": "Type the person's name."}),
    ({}, {"company": "Pick or type a company.", "name": "Type the person's name."}),
])
def test_create_validation(bd_seeded, bd_as_user, bd_db, body, fields):
    r = bd_as_user(BLAIR).post("/api/bd/contacts", json=body)
    assert r.status_code == 400, r.text
    assert r.json() == {"ok": False, "error": "bad_request", "message": "Some fields need fixing.", "fields": fields}
    assert (count(bd_db, "contacts"), count(bd_db, "companies")) == (13, 9)


@pytest.mark.parametrize("body", [["name"], "Ari Mendel", 7])
def test_a_create_body_that_is_not_an_object_is_400_in_one_sentence(bd_seeded, bd_as_user, body):
    r = bd_as_user(BLAIR).post("/api/bd/contacts", json=body)
    assert r.status_code == 400 and r.json()["fields"] == {"body": "Send a JSON object."}, r.text


def test_create_malformed_json_is_400(bd_seeded, bd_as_user):
    r = bd_as_user(BLAIR).post("/api/bd/contacts", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400 and is_envelope(r.json(), "bad_request")


def test_an_unknown_owner_or_company_writes_nothing(bd_seeded, bd_as_user, bd_db):
    for key, msg in (("owner_id", "That owner does not exist."), ("co_owner_id", "That co-owner does not exist.")):
        r = bd_as_user(BLAIR).post("/api/bd/contacts", json={"company": {"name": "Never Made Co"}, "name": "A", key: 99})
        assert r.status_code == 400 and r.json()["message"] == msg and r.json()["fields"] == {key: "Pick a user."}
    r = bd_as_user(BLAIR).post("/api/bd/contacts", json={"company": {"id": 999}, "name": "A"})
    assert r.status_code == 404 and r.json()["message"] == "That company does not exist."
    assert (count(bd_db, "contacts"), count(bd_db, "companies")) == (13, 9)


def test_create_stamps_the_central_time(bd_seeded, bd_as_user, bd_today, monkeypatch):
    """A contact added at 23:30 Central on Nov 4 is a Nov 4 contact, though it is Nov 5 in UTC."""
    monkeypatch.setenv("BD_NOW", "2026-11-04T23:30:00-06:00")
    bd_today(None)
    c = bd_as_user(BLAIR).post("/api/bd/contacts", json={"company": {"name": "Late Co"}, "name": "Night Owl"}).json()
    assert c["contact"]["created_at"] == "2026-11-04T23:30:00-06:00"


# ── POST /api/bd/contacts/{id}/archive (#808) ─────────────────────────────────────────────────
def task_status(bd_db, task_id):
    return bd_db.execute("select status, closed_by_archive, snoozed_until from bd.tasks where id = %s",
                         (task_id,)).fetchone()


def test_archive_and_restore(bd_seeded, bd_as_user, bd_db):
    """Dana's open task 302 (Avery's week of Nov 2) closes with the archive and opens with the
    restore."""
    r = bd_as_user(AVERY).post("/api/bd/contacts/21/archive", json={"archived": True, "reason": " Moved firms "})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["contact"]) == {"id", "archived_at"} and body["contact"]["id"] == 21
    assert body["contact"]["archived_at"].startswith("2026-11-04T") and body["contact"]["archived_at"].endswith("-06:00")
    assert 21 not in ids(bd_as_user(AVERY).get("/api/bd/contacts").json())
    assert task_status(bd_db, 302) == {"status": "snoozed", "closed_by_archive": True, "snoozed_until": None}
    assert bd_as_user(AVERY).get("/api/bd/contacts/21").json()["contact"]["archived_at"] == \
        body["contact"]["archived_at"]
    assert count(bd_db, "interactions") == 8                        # the history is kept
    r = bd_as_user(CASEY).post("/api/bd/contacts/21/archive", json={"archived": False})
    assert r.json() == {"ok": True, "contact": {"id": 21, "archived_at": None}}
    assert task_status(bd_db, 302) == {"status": "open", "closed_by_archive": False, "snoozed_until": None}
    assert [(e["kind"], e["actor_id"], e["detail"]) for e in events(bd_db, 21)] == \
        [("archived", AVERY, "Moved firms"), ("restored", CASEY, None)]


def test_archive_leaves_done_and_skipped_tasks_alone(bd_seeded, bd_as_user, bd_db):
    """Priya's task 303 is done; Sam's 305 was skipped to Nov 10."""
    for cid in (25, 28):
        bd_as_user(CASEY).post("/api/bd/contacts/%d/archive" % cid, json={})
    assert task_status(bd_db, 303) == {"status": "done", "closed_by_archive": False, "snoozed_until": None}
    assert str(task_status(bd_db, 305)["snoozed_until"]) == "2026-11-10"
    assert task_status(bd_db, 305)["closed_by_archive"] is False
    for cid in (25, 28):
        bd_as_user(CASEY).post("/api/bd/contacts/%d/archive" % cid, json={"archived": False})
    assert task_status(bd_db, 303)["status"] == "done"
    assert (task_status(bd_db, 305)["status"], str(task_status(bd_db, 305)["snoozed_until"])) == ("snoozed", "2026-11-10")


def test_a_restore_next_week_keeps_last_weeks_task_closed(bd_seeded, bd_as_user, bd_db, bd_today):
    bd_as_user(AVERY).post("/api/bd/contacts/21/archive", json={})
    bd_today("2026-11-09")
    bd_as_user(AVERY).post("/api/bd/contacts/21/archive", json={"archived": False})
    assert task_status(bd_db, 302) == {"status": "snoozed", "closed_by_archive": False, "snoozed_until": None}


def test_a_restore_late_sunday_central_is_still_this_week(bd_seeded, bd_as_user, bd_db, bd_today, monkeypatch):
    """23:30 Sunday Nov 8 in Central is already Monday in UTC: the week of Nov 2 still counts."""
    bd_as_user(AVERY).post("/api/bd/contacts/21/archive", json={})
    monkeypatch.setenv("BD_NOW", "2026-11-08T23:30:00-06:00")
    bd_today(None)
    bd_as_user(AVERY).post("/api/bd/contacts/21/archive", json={"archived": False})
    assert task_status(bd_db, 302)["status"] == "open"


@pytest.mark.parametrize("role,allowed", [("salesperson", True), ("assistant", True), ("manager", False),
                                          ("admin", True), ("super_admin", True)])
def test_archive_roles(bd_seeded, bd_as_user, bd_db, role, allowed):
    r = bd_as_user(ROLE_IDS[role]).post("/api/bd/contacts/32/archive", json={"archived": True})
    assert r.status_code == (200 if allowed else 403)
    assert (contact_row(bd_db, 32)["archived_at"] is not None) == allowed


def test_archive_errors(bd_seeded, bd_as_user, bd_db):
    r = bd_as_user(BLAIR).post("/api/bd/contacts/999/archive", json={"archived": True})
    assert r.status_code == 404 and r.json()["message"] == "That contact does not exist."
    assert bd_as_user(BLAIR).post("/api/bd/contacts/abc/archive", json={}).status_code == 404
    r = bd_as_user(BLAIR).post("/api/bd/contacts/32/archive", json={"archived": "yes", "reason": 3})
    assert r.status_code == 400 and r.json()["fields"] == {"archived": "Use true or false.", "reason": "Use text."}
    r = bd_as_user(BLAIR).post("/api/bd/contacts/32/archive", json=[True])
    assert r.status_code == 400 and r.json()["fields"] == {"body": "Send a JSON object."}
    assert contact_row(bd_db, 32)["archived_at"] is None and events(bd_db, 32) == []


# ── merge is still a later phase ──────────────────────────────────────────────────────────────
def test_merge_is_still_a_later_phase(bd_seeded, bd_as_user):
    r = bd_as_user(CASEY).post("/api/bd/contacts/33/merge", json={"into_id": 21})
    assert r.status_code == 503 and r.json()["message"] == "This part is not built yet (a later phase)."
    assert bd_as_user(BLAIR).post("/api/bd/contacts/33/merge", json={"into_id": 21}).status_code == 403


def test_the_contact_page_routes_need_a_sign_in(bd_seeded, bd_client):
    for method, path in (("GET", "/api/bd/contacts"), ("GET", "/api/bd/contacts/duplicates"),
                         ("POST", "/api/bd/contacts"), ("POST", "/api/bd/contacts/21/archive")):
        assert bd_client.request(method, path).status_code == 401, (method, path)
