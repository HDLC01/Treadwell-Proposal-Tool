"""The interactions routes under /api/bd/ (#807): GET and POST /api/bd/contacts/{id}/interactions,
PATCH and DELETE /api/bd/interactions/{id} (bd/routers/interactions.py, bd/interactions_service.py).

Moved from BD's tests/test_interactions_api.py. BD ran these on its mock seed and compared a few
sequences with the mock; the mock is gone (#806), so they run on the fixture seed
(bd/ops/fixture_seed.py, today Wed 2026-11-04, CST) with the expected answers worked out here.
This week is Mon Nov 2 .. Sun Nov 8. The people the tests lean on:
    Rory Sandell (22)   Blair's; nothing logged yet; on Blair's Friday batch as task 304 (new, open)
    Dana Whitlow (21)   Avery's; call answered Oct 20 (101), voicemail Nov 2 (102); task 302 (follow-up)
    Priya Nandan (25)   Avery's; a provider's no-answer call Nov 3 (104, logged by nobody); task 303 done
    Nora Lindqvist (31) Avery's maintenance contact, never followed up, so due
Everything is made up: example.com emails, 555-01xx phones.
"""
from __future__ import annotations

import pytest

AVERY, BLAIR, CASEY, DEVON, EMERY, FRANKIE = 1, 2, 3, 4, 5, 6
VM_BODY = {"kind": "call", "outcome": "voicemail", "occurred_at": "2026-11-04T10:05:00-06:00",
           "duration_s": 40, "summary": "Left a voicemail about the dock coating."}


def envelope(r, status, code):
    assert r.status_code == status, (r.status_code, r.text)
    body = r.json()
    assert body["ok"] is False and body["error"] == code, body
    assert isinstance(body["message"], str) and body["message"]
    return body


def log(client, cid, **body):
    return client.post("/api/bd/contacts/%d/interactions" % cid, json=body)


def task_row(db, task_id):
    return db.execute("select * from bd.tasks where id = %s", (task_id,)).fetchone()


def contact_row(db, cid):
    return db.execute("select * from bd.contacts_summary where id = %s", (cid,)).fetchone()


# ── GET /api/bd/contacts/{id}/interactions ───────────────────────────────────────────────────
def test_danas_timeline(bd_seeded, bd_as_user):
    """Newest first: the synthetic "created" event (a workbook contact with no logged one, stamped
    with its created_at today, by whoever ran the latest import: Emery, import 701), then the
    voicemail of Nov 2 (16:00 UTC = 10:00 CST), then the call of Oct 20 (15:00 UTC = 10:00 CDT)."""
    r = bd_as_user(AVERY).get("/api/bd/contacts/21/interactions")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert set(r.json()) == {"ok", "items"}
    assert [i["type"] for i in items] == ["event", "interaction", "interaction"]
    assert items[0]["event"] == {"action": "created", "by": {"id": EMERY, "name": "Emery Stoll"},
                                 "detail": "Imported from the workbook"}
    assert items[0]["at"].startswith("2026-11-04T")
    vm, call = items[1], items[2]
    assert vm["at"] == "2026-11-02T10:00:00-06:00" and vm["interaction"]["id"] == 102
    assert (vm["interaction"]["kind"], vm["interaction"]["outcome"]) == ("voicemail", "voicemail")
    assert call["at"] == "2026-10-20T10:00:00-05:00" and call["interaction"]["id"] == 101
    assert call["interaction"]["counts_as_touch"] is True
    assert call["interaction"]["user"] == {"id": AVERY, "name": "Avery Quill"}
    assert call["interaction"]["contact"] == {"id": 21, "name": "Dana Whitlow",
                                              "company": {"id": 10, "name": "Prairie Ridge Builders LLC"}}


@pytest.mark.parametrize("who", [AVERY, BLAIR, CASEY, DEVON, EMERY, FRANKIE])
def test_the_timeline_is_open_to_every_role(bd_seeded, bd_as_user, who):
    r = bd_as_user(who).get("/api/bd/contacts/21/interactions")
    assert r.status_code == 200
    assert [i["interaction"]["id"] for i in r.json()["items"] if i["type"] == "interaction"] == [102, 101]


@pytest.mark.parametrize("path", ["/api/bd/contacts/999/interactions", "/api/bd/contacts/abc/interactions",
                                  "/api/bd/contacts/0/interactions",
                                  "/api/bd/contacts/99999999999999999999/interactions"])
def test_the_timeline_of_an_unknown_contact_is_404(bd_seeded, bd_as_user, path):
    b = envelope(bd_as_user(AVERY).get(path), 404, "not_found")
    assert b["message"] == "That contact does not exist."


def test_the_interactions_routes_need_a_sign_in(bd_seeded, bd_client):
    for method, path in (("GET", "/api/bd/contacts/21/interactions"), ("POST", "/api/bd/contacts/21/interactions"),
                         ("PATCH", "/api/bd/interactions/101"), ("DELETE", "/api/bd/interactions/101")):
        assert bd_client.request(method, path).status_code == 401, (method, path)


def test_the_timeline_has_event_rows_newest_first_and_a_logged_created_replaces_the_synthetic_one(
        bd_seeded, bd_as_user, bd_db):
    from bd import bizdate, events

    events.log_event(bd_db, "confirmed", actor=CASEY, contact_id=21, at="2026-11-03T09:00:00-06:00")
    events.log_event(bd_db, "owner_changed", actor=None, contact_id=21, detail="Now Blair Fenn",
                     at="2026-11-03T08:00:00-06:00")
    events.log_event(bd_db, "settings_changed", actor=EMERY, contact_id=None)      # no contact: never shown
    items = bd_as_user(AVERY).get("/api/bd/contacts/21/interactions").json()["items"]
    evs = [i for i in items if i["type"] == "event"]
    assert [e["event"]["action"] for e in evs] == ["created", "confirmed", "owner_changed"]
    assert evs[1] == {"type": "event", "at": "2026-11-03T09:00:00-06:00",
                      "event": {"action": "confirmed", "by": {"id": CASEY, "name": "Casey Moret"}, "detail": None}}
    assert evs[2]["event"] == {"action": "owner_changed", "by": None, "detail": "Now Blair Fenn"}
    ats = [bizdate.parse_ts(i["at"]) for i in items]
    assert ats == sorted(ats, reverse=True)
    events.log_event(bd_db, "created", actor=EMERY, contact_id=21, detail="Imported from the workbook",
                     at="2026-01-12T09:00:00-06:00")
    items = bd_as_user(AVERY).get("/api/bd/contacts/21/interactions").json()["items"]
    created = [i for i in items if i["type"] == "event" and i["event"]["action"] == "created"]
    assert [c["at"] for c in created] == ["2026-01-12T09:00:00-06:00"]


def test_a_manual_contact_has_no_synthetic_created_event(bd_seeded, bd_as_user):
    items = bd_as_user(BLAIR).get("/api/bd/contacts/22/interactions").json()["items"]
    assert items == []


def test_the_timeline_shows_central_offsets_across_dst(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("insert into bd.interactions (contact_id, kind, occurred_at, user_id) values"
                  " (22, 'note', '2026-10-30T21:00:00Z', 2), (22, 'note', '2026-11-03T21:00:00Z', 2)")
    ats = [i["at"] for i in bd_as_user(BLAIR).get("/api/bd/contacts/22/interactions").json()["items"]]
    assert ats == ["2026-11-03T15:00:00-06:00", "2026-10-30T16:00:00-05:00"]


# ── POST /api/bd/contacts/{id}/interactions ──────────────────────────────────────────────────
def test_logging_a_voicemail_for_rory(bd_seeded, bd_as_user, bd_db, monkeypatch):
    """The contract's example, on Rory: a voicemail is a call attempt, not a touch. It closes his
    task 304, suggests trying again in a week (Nov 11), and offers the missed-call card."""
    monkeypatch.setenv("BD_NOW", "2026-11-04T10:30:00-06:00")
    r = bd_as_user(BLAIR).post("/api/bd/contacts/22/interactions", json=VM_BODY)
    assert r.status_code == 200, r.text
    got = r.json()
    assert set(got) == {"ok", "interaction", "contact", "task", "recommendation", "missed_call"}
    i = got["interaction"]
    # The fixture's ids end at 108 (interactions) and 402 (recommendations): the next are 109 and 403.
    assert i == {"id": 109, "contact_id": 22,
                 "contact": {"id": 22, "name": "Rory Sandell",
                             "company": {"id": 11, "name": "Prairie Ridge Builders, Inc."}},
                 "kind": "voicemail", "direction": "out", "counts_as_touch": False,
                 "occurred_at": "2026-11-04T10:05:00-06:00", "duration_s": 40, "outcome": "voicemail",
                 "summary": "Left a voicemail about the dock coating.", "transcript": None,
                 "recording_url": None, "provider": "manual", "external_id": None,
                 "user": {"id": BLAIR, "name": "Blair Fenn"}}
    c = got["contact"]
    assert (c["id"], c["last_attempt_at"], c["attempts_since_live"], c["last_live_at"], c["cadence_status"]) == (
        22, "2026-11-04T10:05:00-06:00", 1, None, "never")
    assert got["task"] == {"id": 304, "status": "done", "done_at": "2026-11-04T10:05:00-06:00"}
    rec = got["recommendation"]
    assert (rec["id"], rec["interaction_id"], rec["action"], rec["due_date"], rec["reason"], rec["source"],
            rec["status"], rec["created_at"]) == (403, 109, "Try Rory again", "2026-11-11",
                                                  "Voicemail. Try again in a week.", "fallback", "pending",
                                                  "2026-11-04T10:30:00-06:00")
    assert got["missed_call"] is True
    assert task_row(bd_db, 304)["status"] == "done"


def test_a_logged_call_shows_in_the_contacts_history(bd_seeded, bd_as_user):
    """#807's acceptance: a salesperson logs a call from This Week and it is on the contact's timeline."""
    blair = bd_as_user(BLAIR)
    iid = log(blair, 22, kind="call", outcome="answered", occurred_at="2026-11-04T09:00:00-06:00",
              summary="Wants a price for the shop floor.").json()["interaction"]["id"]
    items = blair.get("/api/bd/contacts/22/interactions").json()["items"]
    assert [(i["type"], i["interaction"]["id"], i["interaction"]["summary"]) for i in items] == [
        ("interaction", iid, "Wants a price for the shop floor.")]


TOUCH_CASES = [
    ("call", "answered", "call", "answered", True),
    ("call", "meeting_set", "call", "meeting_set", True),
    ("call", "no_answer", "call", "no_answer", False),
    ("call", "voicemail", "voicemail", "voicemail", False),
    ("voicemail", None, "voicemail", "voicemail", False),
    ("voicemail", "answered", "voicemail", "voicemail", False),
    ("meeting", None, "meeting", None, True),
    ("meeting", "answered", "meeting", None, True),
    ("hosted", None, "hosted", None, True),
    ("email", None, "email", None, False),
    ("sms", "answered", "sms", None, False),
    ("note", None, "note", None, False),
]


@pytest.mark.parametrize("kind,outcome,stored_kind,stored_outcome,touch", TOUCH_CASES)
def test_the_counting_rule_is_the_servers_and_ignores_the_client(bd_seeded, bd_as_user, bd_db, kind, outcome,
                                                                 stored_kind, stored_outcome, touch):
    body = {"kind": kind, "occurred_at": "2026-11-04T09:00:00-06:00", "counts_as_touch": not touch}
    if outcome is not None:
        body["outcome"] = outcome
    r = log(bd_as_user(BLAIR), 22, **body)
    assert r.status_code == 200, r.text
    i = r.json()["interaction"]
    assert (i["kind"], i["outcome"], i["counts_as_touch"]) == (stored_kind, stored_outcome, touch)
    stored = bd_db.execute("select kind, outcome, counts_as_touch from bd.interactions where id = %s",
                           (i["id"],)).fetchone()
    assert (stored["kind"], stored["outcome"], stored["counts_as_touch"]) == (stored_kind, stored_outcome, touch)
    c = r.json()["contact"]
    assert (c["last_live_at"] is not None) == touch
    assert c["touches_this_year"] == (1 if touch else 0)
    assert c["cadence_status"] == ("on_track" if touch else "never")
    if stored_kind in ("call", "voicemail"):
        assert c["last_attempt_at"] == "2026-11-04T09:00:00-06:00"
        assert c["attempts_since_live"] == (0 if touch else 1)
    else:
        assert c["last_attempt_at"] is None
    assert i["direction"] == (None if stored_kind in ("meeting", "hosted", "note") else "out")
    closes = stored_kind in ("call", "voicemail", "meeting", "hosted")
    assert (r.json()["task"] is not None) == closes
    assert task_row(bd_db, 304)["status"] == ("done" if closes else "open")
    assert (r.json()["recommendation"] is not None) == closes
    assert r.json()["missed_call"] == (stored_kind == "voicemail" or stored_outcome == "no_answer")


def test_occurred_at_defaults_to_now_central(bd_seeded, bd_as_user, monkeypatch):
    monkeypatch.setenv("BD_NOW", "2026-11-04T16:20:07Z")
    r = log(bd_as_user(BLAIR), 22, kind="call", outcome="answered")
    assert r.json()["interaction"]["occurred_at"] == "2026-11-04T10:20:07-06:00"
    assert r.json()["task"]["done_at"] == "2026-11-04T10:20:07-06:00"
    assert r.json()["recommendation"]["created_at"] == "2026-11-04T10:20:07-06:00"


def test_summary_and_transcript_defaults(bd_seeded, bd_as_user):
    i = log(bd_as_user(BLAIR), 22, kind="note").json()["interaction"]
    assert i["summary"] == "" and i["transcript"] is None and i["duration_s"] is None
    i = log(bd_as_user(BLAIR), 22, kind="call", outcome="answered", duration_s="95", transcript="T: hi",
            direction="in").json()["interaction"]
    assert i["duration_s"] == 95 and i["transcript"] == "T: hi" and i["direction"] == "in"


@pytest.mark.parametrize("who", [AVERY, BLAIR, EMERY, FRANKIE])
def test_salespeople_and_admins_log_anything(bd_seeded, bd_as_user, who):
    assert log(bd_as_user(who), 22, kind="meeting").status_code == 200


def test_a_manager_may_not_log(bd_seeded, bd_as_user, bd_db):
    body = envelope(log(bd_as_user(DEVON), 22, kind="note"), 403, "forbidden")
    assert body["message"] == "Your role can't do that."
    assert bd_db.execute("select count(*) as n from bd.interactions where contact_id = 22").fetchone()["n"] == 0


def test_an_assistant_logs_notes_only(bd_seeded, bd_as_user, bd_db):
    r = log(bd_as_user(CASEY), 22, kind="note", summary="Front desk says Rory is out until Monday.")
    assert r.status_code == 200
    assert r.json()["task"] is None and r.json()["recommendation"] is None
    assert r.json()["interaction"]["user"] == {"id": CASEY, "name": "Casey Moret"}
    for kind in ("call", "voicemail", "meeting", "email", "sms", "hosted", None):
        body = {"outcome": "answered"} if kind is None else {"kind": kind, "outcome": "answered"}
        b = envelope(bd_as_user(CASEY).post("/api/bd/contacts/22/interactions", json=body), 403, "forbidden")
        assert b["message"] == "Assistants can add notes only."
    assert task_row(bd_db, 304)["status"] == "open"


def test_a_role_check_comes_before_the_404(bd_seeded, bd_as_user):
    envelope(log(bd_as_user(DEVON), 999, kind="note"), 403, "forbidden")
    envelope(log(bd_as_user(CASEY), 999, kind="call", outcome="answered"), 403, "forbidden")
    envelope(log(bd_as_user(CASEY), 999, kind="note"), 404, "not_found")
    b = envelope(log(bd_as_user(BLAIR), 999, kind="bogus"), 404, "not_found")
    assert b["message"] == "That contact does not exist."


BAD_BODIES = [
    ({}, "kind", "Pick what happened."),
    ({"kind": "lunch"}, "kind", "Pick what happened."),
    ({"kind": "Call", "outcome": "answered"}, "kind", "Pick what happened."),
    ({"kind": 3}, "kind", "Pick what happened."),
    ({"kind": "call"}, "outcome", "Pick how the call went."),
    ({"kind": "call", "outcome": "busy"}, "outcome", "Pick how the call went."),
    ({"kind": "note", "occurred_at": "yesterday"}, "occurred_at", None),
    ({"kind": "note", "occurred_at": "2026-11-04"}, "occurred_at", None),
    ({"kind": "note", "occurred_at": 1730000000}, "occurred_at", None),
    ({"kind": "note", "occurred_at": "2026-11-05T09:00:00-06:00"}, "occurred_at", "That time is in the future."),
    ({"kind": "note", "occurred_at": "0001-01-01T00:00:00Z"}, "occurred_at", None),
    ({"kind": "note", "duration_s": -1}, "duration_s", None),
    ({"kind": "note", "duration_s": "forty"}, "duration_s", None),
    ({"kind": "note", "duration_s": True}, "duration_s", None),
    ({"kind": "note", "duration_s": 1.5}, "duration_s", None),
    ({"kind": "note", "duration_s": 2 ** 40}, "duration_s", None),
    ({"kind": "note", "summary": 12}, "summary", None),
    ({"kind": "note", "summary": "x" * 20001}, "summary", None),
    ({"kind": "note", "transcript": ["a"]}, "transcript", None),
    ({"kind": "call", "outcome": "answered", "direction": "sideways"}, "direction", None),
]


@pytest.mark.parametrize("body,field,message", BAD_BODIES)
def test_bad_input_is_400_with_fields_and_logs_nothing(bd_seeded, bd_as_user, bd_db, body, field, message):
    b = envelope(bd_as_user(BLAIR).post("/api/bd/contacts/22/interactions", json=body), 400, "bad_request")
    assert field in b["fields"], b
    if message:
        assert b["message"] == message
    assert bd_db.execute("select count(*) as n from bd.interactions where contact_id = 22").fetchone()["n"] == 0
    assert task_row(bd_db, 304)["status"] == "open"


def test_a_body_that_is_not_an_object_or_not_json_is_400(bd_seeded, bd_as_user):
    blair = bd_as_user(BLAIR)
    b = envelope(blair.post("/api/bd/contacts/22/interactions", json=["note"]), 400, "bad_request")
    # One sentence for a body that is not an object, on every BD route that reads one (bd/paging.py).
    assert b["fields"] == {"body": "Send a JSON object."}
    b = envelope(blair.patch("/api/bd/interactions/101", json="call"), 400, "bad_request")
    assert b["fields"] == {"body": "Send a JSON object."}
    envelope(blair.post("/api/bd/contacts/22/interactions", content=b"{kind: note",
                        headers={"Content-Type": "application/json"}), 400, "bad_request")


@pytest.mark.parametrize("at,expect_ok,shown", [
    ("2026-11-04T23:59:59-06:00", True, "2026-11-04T23:59:59-06:00"),
    ("2026-11-05T05:30:00Z", True, "2026-11-04T23:30:00-06:00"),       # still Nov 4 in Central
    ("2026-11-05T06:00:00Z", False, None),                              # 00:00 Nov 5 Central
    ("2026-11-04T23:00:00", True, "2026-11-04T23:00:00-06:00"),         # naive = Central wall clock
    ("2026-10-30T21:00:00Z", True, "2026-10-30T16:00:00-05:00"),        # CDT keeps its offset
    ("2026-11-01T01:30:00-05:00", True, "2026-11-01T01:30:00-05:00"),   # the repeated hour, first pass
    ("2026-11-01T01:30:00-06:00", True, "2026-11-01T01:30:00-06:00"),   # ... and second
])
def test_future_means_after_today_in_central(bd_seeded, bd_as_user, at, expect_ok, shown):
    r = log(bd_as_user(BLAIR), 22, kind="note", occurred_at=at)
    if expect_ok:
        assert r.status_code == 200, r.text
        assert r.json()["interaction"]["occurred_at"] == shown
    else:
        envelope(r, 400, "bad_request")


def test_touches_this_year_splits_at_central_midnight_on_new_year(bd_seeded, bd_as_user, bd_today):
    bd_today("2027-01-01")
    blair = bd_as_user(BLAIR)
    c = log(blair, 22, kind="call", outcome="answered", occurred_at="2027-01-01T05:30:00Z").json()["contact"]
    assert c["touches_this_year"] == 0                   # 23:30 Dec 31 Central: last year
    assert c["last_live_at"] == "2026-12-31T23:30:00-06:00"
    assert c["next_due_date"] == "2027-04-01"            # the BD cadence, quarterly: Dec 31 + 91
    assert c["cadence_status"] == "on_track"
    c = log(blair, 22, kind="call", outcome="answered", occurred_at="2027-01-01T06:10:00Z").json()["contact"]
    assert c["touches_this_year"] == 1


def test_a_touch_on_or_after_the_promised_date_clears_it_and_the_next_step(bd_seeded, bd_as_user, bd_db):
    bd_db.execute("update bd.contacts set promised_date = '2026-11-04', next_step = 'Call back',"
                  " next_step_date = '2026-11-04' where id = 22")
    blair = bd_as_user(BLAIR)
    # 23:30 Nov 3 Central: before the promise, so it stays.
    c = log(blair, 22, kind="call", outcome="answered", occurred_at="2026-11-04T05:30:00Z").json()["contact"]
    assert c["promised_date"] == "2026-11-04" and c["next_step"] == "Call back"
    # A voicemail is not a touch: it stays.
    c = log(blair, 22, kind="voicemail", occurred_at="2026-11-04T09:00:00-06:00").json()["contact"]
    assert c["promised_date"] == "2026-11-04" and c["next_step_date"] == "2026-11-04"
    # 00:30 Nov 4 Central: on the day, cleared.
    c = log(blair, 22, kind="meeting", occurred_at="2026-11-04T06:30:00Z").json()["contact"]
    assert c["promised_date"] is None and c["next_step"] is None and c["next_step_date"] is None


def test_a_touch_before_the_promise_keeps_it(bd_seeded, bd_as_user):
    # Dana (21): promised a call by Thu Nov 5, next step due Fri Nov 6.
    c = log(bd_as_user(AVERY), 21, kind="call", outcome="answered",
            occurred_at="2026-11-04T09:00:00-06:00").json()["contact"]
    assert c["promised_date"] == "2026-11-05" and c["next_step_date"] == "2026-11-06"


def test_a_done_task_is_not_closed_again(bd_seeded, bd_as_user, bd_db):
    before = task_row(bd_db, 303)
    r = log(bd_as_user(AVERY), 25, kind="call", outcome="answered", occurred_at="2026-11-04T09:00:00-06:00")
    assert r.json()["task"] is None
    assert task_row(bd_db, 303)["done_at"] == before["done_at"]


def test_only_this_weeks_task_closes(bd_seeded, bd_as_user, bd_db):
    b = bd_db.execute("insert into bd.task_batches (owner_id, week_start, kind) values (1, '2026-10-26', 'friday')"
                      " returning id").fetchone()["id"]
    old = bd_db.execute("insert into bd.tasks (batch_id, contact_id, kind) values (%s, 27, 'new') returning id",
                        (b,)).fetchone()["id"]
    r = log(bd_as_user(AVERY), 27, kind="call", outcome="answered", occurred_at="2026-11-04T09:00:00-06:00")
    assert r.json()["task"] is None
    assert task_row(bd_db, old)["status"] == "open"


def test_the_week_is_central_monday_to_sunday(bd_seeded, bd_as_user, bd_today, bd_db):
    bd_today("2026-11-08")                     # Sunday Nov 8 is still the week of Nov 2
    assert log(bd_as_user(BLAIR), 22, kind="voicemail").json()["task"]["id"] == 304
    bd_db.execute("update bd.tasks set status = 'open', done_at = null where id = 304")
    bd_today("2026-11-09")                     # Monday Nov 9 is not
    assert log(bd_as_user(BLAIR), 22, kind="voicemail").json()["task"] is None
    assert task_row(bd_db, 304)["status"] == "open"


def test_a_backdated_call_still_closes_this_weeks_task_at_its_time(bd_seeded, bd_as_user):
    r = log(bd_as_user(BLAIR), 22, kind="call", outcome="no_answer", occurred_at="2026-10-28T10:00:00-05:00")
    assert r.json()["task"] == {"id": 304, "status": "done", "done_at": "2026-10-28T10:00:00-05:00"}


def test_every_open_task_of_the_company_this_week_closes_and_the_latest_is_answered(bd_seeded, bd_as_user, bd_db):
    """#828: a meeting with Rory (22) closes the company's row: his Friday task 304 and a later list's
    task for him both close, and the answer is the latest of his own."""
    b = bd_db.execute("insert into bd.task_batches (owner_id, week_start, kind) values (2, '2026-11-02', 'ten_more')"
                      " returning id").fetchone()["id"]
    t = bd_db.execute("insert into bd.tasks (batch_id, contact_id, kind) values (%s, 22, 'new') returning id",
                      (b,)).fetchone()["id"]
    r = log(bd_as_user(BLAIR), 22, kind="meeting", occurred_at="2026-11-04T09:00:00-06:00")
    assert r.json()["task"]["id"] == t
    assert task_row(bd_db, 304)["status"] == "done"


def _maintenance_task(db, cid=31):
    """An open maintenance task for Nora (due) on Avery's live Friday batch 201."""
    return db.execute("insert into bd.tasks (batch_id, contact_id, kind, reason, reasons, score)"
                      " values (201, %s, 'maintenance', 'No follow-up logged yet.',"
                      " array['No follow-up logged yet'], 48) returning id", (cid,)).fetchone()["id"]


def _later_maintenance_task(db, week_start="2026-11-09", cid=31):
    b = db.execute("insert into bd.task_batches (owner_id, week_start, kind) values (1, %s, 'friday')"
                   " returning id", (week_start,)).fetchone()["id"]
    return db.execute("insert into bd.tasks (batch_id, contact_id, kind) values (%s, %s, 'maintenance') returning id",
                      (b, cid)).fetchone()["id"]


@pytest.mark.parametrize("body, closes", [
    ({"kind": "email", "summary": "Sent the spring schedule."}, True),
    ({"kind": "sms", "summary": "Texted to confirm."}, True),
    ({"kind": "call", "outcome": "answered"}, True),
    ({"kind": "call", "outcome": "no_answer"}, True),
    ({"kind": "call", "outcome": "voicemail"}, True),
    ({"kind": "call", "outcome": "meeting_set"}, True),
    ({"kind": "voicemail"}, True),
    ({"kind": "meeting"}, True),
    ({"kind": "hosted"}, True),
    ({"kind": "note", "summary": "Thinking about this one."}, False),
])
def test_any_follow_up_but_a_note_closes_a_maintenance_task(bd_seeded, bd_as_user, bd_db, body, closes):
    tid = _maintenance_task(bd_db)
    assert contact_row(bd_db, 31)["maintenance_due"] is True
    r = log(bd_as_user(AVERY), 31, occurred_at="2026-11-04T09:00:00-06:00", **body)
    assert r.status_code == 200, r.text
    assert (r.json()["task"] is not None) == closes
    assert task_row(bd_db, tid)["status"] == ("done" if closes else "open")
    if closes:
        assert r.json()["task"] == {"id": tid, "status": "done", "done_at": "2026-11-04T09:00:00-06:00"}
    assert contact_row(bd_db, 31)["maintenance_due"] is (not closes)
    assert (r.json()["recommendation"] is not None) == (body["kind"] in ("call", "voicemail", "meeting", "hosted"))


def test_an_email_leaves_a_new_or_followup_task_open(bd_seeded, bd_as_user, bd_db):
    for who, cid, tid in ((BLAIR, 22, 304), (AVERY, 21, 302)):     # a "new" task and a "followup" task
        for kind in ("email", "sms", "note"):
            r = log(bd_as_user(who), cid, kind=kind, summary="x", occurred_at="2026-11-04T09:00:00-06:00")
            assert r.status_code == 200 and r.json()["task"] is None, (cid, kind)
            assert task_row(bd_db, tid)["status"] == "open"
    assert log(bd_as_user(BLAIR), 22, kind="call", outcome="answered").json()["task"]["id"] == 304


def test_a_maintenance_task_that_is_done_is_not_closed_again(bd_seeded, bd_as_user, bd_db):
    tid = _maintenance_task(bd_db)
    first = log(bd_as_user(AVERY), 31, kind="email", summary="a", occurred_at="2026-11-04T09:00:00-06:00")
    assert first.json()["task"]["id"] == tid
    done_at = task_row(bd_db, tid)["done_at"]
    second = log(bd_as_user(AVERY), 31, kind="email", summary="b", occurred_at="2026-11-04T09:30:00-06:00")
    assert second.json()["task"] is None and task_row(bd_db, tid)["done_at"] == done_at


def test_a_follow_up_closes_the_pinned_task_of_next_weeks_list_too(bd_seeded, bd_as_user, bd_db, bd_today):
    """Next week's list is built on Friday; an email logged on the Saturday clears Nora, so it
    clears that task too."""
    bd_today("2026-11-07")
    nxt = _later_maintenance_task(bd_db)
    mine = _maintenance_task(bd_db)
    r = log(bd_as_user(AVERY), 31, kind="email", summary="Sent the price.", occurred_at="2026-11-07T09:00:00-06:00")
    assert r.status_code == 200, r.text
    assert r.json()["task"] == {"id": mine, "status": "done", "done_at": "2026-11-07T09:00:00-06:00"}
    assert task_row(bd_db, nxt)["status"] == "done" and task_row(bd_db, mine)["status"] == "done"
    assert contact_row(bd_db, 31)["maintenance_due"] is False


def test_the_answer_names_next_weeks_task_when_it_is_the_only_one(bd_seeded, bd_as_user, bd_db, bd_today):
    bd_today("2026-11-07")
    nxt = _later_maintenance_task(bd_db)
    r = log(bd_as_user(AVERY), 31, kind="sms", summary="Texted.", occurred_at="2026-11-07T09:00:00-06:00")
    assert r.json()["task"] == {"id": nxt, "status": "done", "done_at": "2026-11-07T09:00:00-06:00"}


def test_a_follow_up_leaves_an_earlier_weeks_maintenance_task_alone(bd_seeded, bd_as_user, bd_db):
    old = _later_maintenance_task(bd_db, "2026-10-26")
    r = log(bd_as_user(AVERY), 31, kind="email", summary="x", occurred_at="2026-11-04T09:00:00-06:00")
    assert r.json()["task"] is None and task_row(bd_db, old)["status"] == "open"


def test_a_note_leaves_next_weeks_maintenance_task_open(bd_seeded, bd_as_user, bd_db):
    nxt = _later_maintenance_task(bd_db)
    r = log(bd_as_user(AVERY), 31, kind="note", summary="Thinking.", occurred_at="2026-11-04T09:00:00-06:00")
    assert r.json()["task"] is None and task_row(bd_db, nxt)["status"] == "open"
    assert contact_row(bd_db, 31)["maintenance_due"] is True


def test_a_backdated_email_that_leaves_the_contact_due_closes_nothing(bd_seeded, bd_as_user, bd_db):
    """An email dated May 1 puts the next follow-up at Aug 29, still before today: Nora stays due
    and her pinned task stays (and still refuses to be taken off by hand)."""
    tid = _maintenance_task(bd_db)
    r = log(bd_as_user(AVERY), 31, kind="email", summary="Old thread.", occurred_at="2026-05-01T09:00:00-05:00")
    assert r.status_code == 200, r.text
    assert r.json()["task"] is None and task_row(bd_db, tid)["status"] == "open"
    assert contact_row(bd_db, 31)["maintenance_due"] is True
    assert bd_as_user(AVERY).post("/api/bd/tasks/%d/snooze" % tid, json={}).status_code == 409
    r = log(bd_as_user(AVERY), 31, kind="email", summary="Today.", occurred_at="2026-11-04T09:00:00-06:00")
    assert r.json()["task"]["id"] == tid and task_row(bd_db, tid)["status"] == "done"


def test_editing_a_note_into_an_email_closes_the_pinned_task(bd_seeded, bd_as_user, bd_db):
    tid = _maintenance_task(bd_db)
    nxt = _later_maintenance_task(bd_db)
    iid = log(bd_as_user(AVERY), 31, kind="note", summary="Draft.",
              occurred_at="2026-11-04T09:00:00-06:00").json()["interaction"]["id"]
    assert task_row(bd_db, tid)["status"] == "open"
    r = bd_as_user(AVERY).patch("/api/bd/interactions/%d" % iid, json={"kind": "email"})
    assert r.status_code == 200, r.text
    assert contact_row(bd_db, 31)["maintenance_due"] is False
    assert task_row(bd_db, tid)["status"] == "done" and task_row(bd_db, nxt)["status"] == "done"


def test_the_close_rule_by_kind():
    from bd import interactions_service as svc
    assert svc.MAINTENANCE_CLOSE_KINDS == ("call", "voicemail", "meeting", "email", "sms", "hosted")
    assert svc.TASK_KINDS == ("call", "voicemail", "meeting", "hosted")
    for k in ("call", "voicemail", "meeting", "email", "sms", "note", "hosted"):
        assert svc.closes_task("maintenance", k) == (k != "note")
        assert svc.closes_task("new", k) == (k in ("call", "voicemail", "meeting", "hosted"))
        assert svc.closes_task("followup", k) == (k in ("call", "voicemail", "meeting", "hosted"))


def test_recommendations_follow_the_fallback_table(bd_seeded, bd_as_user):
    blair = bd_as_user(BLAIR)
    rec = log(blair, 22, kind="voicemail", summary="").json()["recommendation"]
    assert (rec["action"], rec["due_date"], rec["reason"]) == ("Try Rory again", "2026-11-11",
                                                               "Voicemail. Try again in a week.")
    assert rec["status"] == "pending" and rec["source"] == "fallback" and rec["decided_by"] is None
    rec = log(blair, 22, kind="call", outcome="no_answer").json()["recommendation"]
    assert rec["reason"] == "No answer. Try again in a week."
    rec = log(blair, 22, kind="call", outcome="answered", summary="Call me next month.").json()["recommendation"]
    assert (rec["action"], rec["due_date"]) == ("Call back on the date they asked for", "2026-12-04")
    assert rec["reason"] == "They said “next month”. Call on Fri, Dec 4."
    # 105 days after Nov 4: 26 to Nov 30, 31 in December, 31 in January, 17 in February.
    rec = log(blair, 22, kind="hosted").json()["recommendation"]
    assert rec["due_date"] == "2027-02-17"
    assert rec["reason"] == "Met in person. Check in again in about 3–4 months."


def test_one_transaction_a_failure_leaves_nothing_behind(bd_seeded, bd_as_user, bd_db, monkeypatch):
    from bd import interactions_service

    def boom(*a, **k):
        raise RuntimeError("recommendation store down")
    monkeypatch.setattr(interactions_service, "make_recommendation", boom)
    bd_db.execute("update bd.contacts set promised_date = '2026-11-01' where id = 22")
    r = log(bd_as_user(BLAIR), 22, kind="call", outcome="answered", occurred_at="2026-11-04T09:00:00-06:00")
    envelope(r, 500, "error")
    assert bd_db.execute("select count(*) as n from bd.interactions where contact_id = 22").fetchone()["n"] == 0
    assert task_row(bd_db, 304)["status"] == "open"
    assert str(contact_row(bd_db, 22)["promised_date"]) == "2026-11-01"


# ── PATCH /api/bd/interactions/{id} ──────────────────────────────────────────────────────────
def test_patch_a_voicemail_into_an_answered_call(bd_seeded, bd_as_user, bd_db):
    blair = bd_as_user(BLAIR)
    iid = log(blair, 22, **VM_BODY).json()["interaction"]["id"]
    r = blair.patch("/api/bd/interactions/%d" % iid,
                    json={"outcome": "answered", "summary": "Picked up after all. Wants a price in December."})
    assert r.status_code == 200, r.text
    got = r.json()["interaction"]
    assert (got["id"], got["kind"], got["outcome"], got["counts_as_touch"], got["direction"]) == (
        iid, "call", "answered", True, "out")
    assert got["summary"] == "Picked up after all. Wants a price in December."
    c = contact_row(bd_db, 22)
    assert c["cadence_status"] == "on_track" and c["touches_this_year"] == 1 and c["attempts_since_live"] == 0
    blair.patch("/api/bd/interactions/%d" % iid, json={"kind": "note"})
    c = contact_row(bd_db, 22)
    assert c["cadence_status"] == "never" and c["last_live_at"] is None and c["last_attempt_at"] is None
    i = bd_db.execute("select kind, outcome, counts_as_touch, direction from bd.interactions where id = %s",
                      (iid,)).fetchone()
    assert (i["kind"], i["outcome"], i["counts_as_touch"], i["direction"]) == ("note", None, False, None)


def test_patch_moving_the_time_moves_last_live(bd_seeded, bd_as_user, bd_db):
    blair = bd_as_user(BLAIR)
    iid = log(blair, 22, kind="call", outcome="answered",
              occurred_at="2026-11-04T09:00:00-06:00").json()["interaction"]["id"]
    # The BD cadence is quarterly (+91 days). Moved to Mar 2 (CST), due Jun 1: behind.
    r = blair.patch("/api/bd/interactions/%d" % iid, json={"occurred_at": "2026-03-02T09:00:00-06:00",
                                                           "duration_s": 60})
    assert r.json()["interaction"]["occurred_at"] == "2026-03-02T09:00:00-06:00"
    assert r.json()["interaction"]["duration_s"] == 60
    c = contact_row(bd_db, 22)
    assert str(c["next_due_date"]) == "2026-06-01" and c["cadence_status"] == "behind"
    r = blair.patch("/api/bd/interactions/%d" % iid, json={"occurred_at": "2026-08-03T14:00:00Z"})
    assert r.json()["interaction"]["occurred_at"] == "2026-08-03T09:00:00-05:00"


@pytest.mark.parametrize("body,kind,outcome,touch", [
    ({"outcome": "answered"}, "call", "answered", True),          # a voicemail picked up after all
    ({"kind": "call", "outcome": "no_answer"}, "call", "no_answer", False),
    ({"kind": "meeting"}, "meeting", None, True),
    ({"kind": "call", "outcome": "voicemail"}, "voicemail", "voicemail", False),
    ({"summary": "only words"}, "voicemail", "voicemail", False),
    ({"counts_as_touch": True}, "voicemail", "voicemail", False),
    ({}, "voicemail", "voicemail", False),
])
def test_patch_kind_and_outcome_follow_the_counting_rule(bd_seeded, bd_as_user, body, kind, outcome, touch):
    blair = bd_as_user(BLAIR)
    iid = log(blair, 22, **VM_BODY).json()["interaction"]["id"]
    got = blair.patch("/api/bd/interactions/%d" % iid, json=body).json()["interaction"]
    assert (got["kind"], got["outcome"], got["counts_as_touch"]) == (kind, outcome, touch)


@pytest.mark.parametrize("who", [BLAIR, CASEY, DEVON])
def test_only_the_logger_or_an_admin_may_patch(bd_seeded, bd_as_user, who):
    # 101 is Avery's call: another salesperson, the assistant and the manager may not change it.
    b = envelope(bd_as_user(who).patch("/api/bd/interactions/101", json={"summary": "x"}), 403, "forbidden")
    assert b["message"] == "Only the person who logged this can change it."


@pytest.mark.parametrize("who", [EMERY, FRANKIE])
def test_an_admin_may_patch_anyones(bd_seeded, bd_as_user, who):
    r = bd_as_user(who).patch("/api/bd/interactions/101", json={"summary": "Fixed by an admin."})
    assert r.status_code == 200 and r.json()["interaction"]["summary"] == "Fixed by an admin."
    assert r.json()["interaction"]["user"] == {"id": AVERY, "name": "Avery Quill"}       # still Avery's


def test_a_call_with_no_logger_is_admin_only(bd_seeded, bd_as_user):
    # 104: the phone provider's call on Priya, logged by nobody.
    envelope(bd_as_user(AVERY).patch("/api/bd/interactions/104", json={"summary": "x"}), 403, "forbidden")
    assert bd_as_user(EMERY).patch("/api/bd/interactions/104", json={"summary": "x"}).status_code == 200


def test_an_assistant_edits_her_note_but_cannot_make_it_a_call(bd_seeded, bd_as_user, bd_db):
    casey = bd_as_user(CASEY)
    iid = log(casey, 22, kind="note", summary="Front desk").json()["interaction"]["id"]
    r = casey.patch("/api/bd/interactions/%d" % iid, json={"summary": "Front desk says Monday."})
    assert r.status_code == 200 and r.json()["interaction"]["summary"] == "Front desk says Monday."
    b = envelope(casey.patch("/api/bd/interactions/%d" % iid, json={"kind": "call", "outcome": "answered"}),
                 403, "forbidden")
    assert b["message"] == "Assistants can add notes only."
    assert bd_db.execute("select kind from bd.interactions where id = %s", (iid,)).fetchone()["kind"] == "note"


@pytest.mark.parametrize("path", ["/api/bd/interactions/99999", "/api/bd/interactions/abc",
                                  "/api/bd/interactions/0"])
def test_patch_unknown_is_404(bd_seeded, bd_as_user, path):
    b = envelope(bd_as_user(EMERY).patch(path, json={"summary": "x"}), 404, "not_found")
    assert b["message"] == "That interaction does not exist."


def test_patch_404_comes_before_the_owner_check(bd_seeded, bd_as_user):
    envelope(bd_as_user(DEVON).patch("/api/bd/interactions/99999", json={}), 404, "not_found")


@pytest.mark.parametrize("body,field", [
    ({"kind": "lunch"}, "kind"),
    ({"kind": "call", "outcome": "busy"}, "outcome"),
    ({"outcome": "busy"}, "outcome"),                      # on the voicemail: a call outcome is needed
    ({"occurred_at": "2026-11-05T08:00:00-06:00"}, "occurred_at"),
    ({"occurred_at": None}, "occurred_at"),
    ({"occurred_at": "soon"}, "occurred_at"),
    ({"duration_s": -5}, "duration_s"),
    ({"summary": {"a": 1}}, "summary"),
    ({"transcript": 5}, "transcript"),
])
def test_patch_bad_input_is_400_and_changes_nothing(bd_seeded, bd_as_user, bd_db, body, field):
    blair = bd_as_user(BLAIR)
    iid = log(blair, 22, **VM_BODY).json()["interaction"]["id"]
    before = bd_db.execute("select * from bd.interactions where id = %s", (iid,)).fetchone()
    b = envelope(blair.patch("/api/bd/interactions/%d" % iid, json=body), 400, "bad_request")
    assert field in b["fields"]
    assert bd_db.execute("select * from bd.interactions where id = %s", (iid,)).fetchone() == before


def test_patch_kind_call_on_a_note_needs_an_outcome(bd_seeded, bd_as_user):
    blair = bd_as_user(BLAIR)
    iid = log(blair, 22, kind="note").json()["interaction"]["id"]
    b = envelope(blair.patch("/api/bd/interactions/%d" % iid, json={"kind": "call"}), 400, "bad_request")
    assert b["message"] == "Pick how the call went."


def test_patch_does_not_close_tasks_or_add_recommendations(bd_seeded, bd_as_user, bd_db):
    blair = bd_as_user(BLAIR)
    iid = log(blair, 22, kind="note").json()["interaction"]["id"]
    blair.patch("/api/bd/interactions/%d" % iid, json={"kind": "call", "outcome": "answered"})
    assert task_row(bd_db, 304)["status"] == "open"
    assert bd_db.execute("select count(*) as n from bd.ai_recommendations where interaction_id = %s",
                         (iid,)).fetchone()["n"] == 0


# ── DELETE /api/bd/interactions/{id} ─────────────────────────────────────────────────────────
def test_delete_recomputes_and_is_audited(bd_seeded, bd_as_user, bd_db):
    """Deleting 101, Dana's only live talk: she has no live talk left, the recommendation it made
    (401) keeps its row with the link gone, and the audit row names no contact."""
    before = contact_row(bd_db, 21)
    assert before["touches_this_year"] == 1 and before["last_live_at"] is not None
    r = bd_as_user(EMERY).delete("/api/bd/interactions/101")
    assert r.status_code == 200 and r.json() == {"ok": True, "deleted": 101}
    assert bd_db.execute("select 1 from bd.interactions where id = 101").fetchone() is None
    after = contact_row(bd_db, 21)
    assert after["last_live_at"] is None and after["touches_this_year"] == 0
    rec = bd_db.execute("select interaction_id, status from bd.ai_recommendations where id = 401").fetchone()
    assert rec == {"interaction_id": None, "status": "pending"}
    ids = [i["interaction"]["id"] for i in bd_as_user(AVERY).get("/api/bd/contacts/21/interactions").json()["items"]
           if i["type"] == "interaction"]
    assert ids == [102]
    audit = bd_db.execute("select * from bd.events where kind = 'interaction_deleted'").fetchone()
    assert audit["contact_id"] is None and audit["actor_id"] == EMERY
    assert audit["data"]["interaction_id"] == 101 and audit["data"]["contact_id"] == 21
    assert audit["data"]["occurred_at"] == "2026-10-20T10:00:00-05:00"


def test_delete_a_call_with_a_followup_draft(bd_seeded, bd_as_user, bd_db):
    assert bd_as_user(FRANKIE).delete("/api/bd/interactions/104").status_code == 200
    assert bd_db.execute("select interaction_id from bd.followup_drafts where id = 501").fetchone() == \
        {"interaction_id": None}


@pytest.mark.parametrize("who", [AVERY, BLAIR, CASEY, DEVON])
def test_delete_is_admin_only_and_403_comes_first(bd_seeded, bd_as_user, bd_db, who):
    b = envelope(bd_as_user(who).delete("/api/bd/interactions/101"), 403, "forbidden")
    assert b["message"] == "Your role can't do that."
    envelope(bd_as_user(who).delete("/api/bd/interactions/99999"), 403, "forbidden")
    assert bd_db.execute("select 1 from bd.interactions where id = 101").fetchone() is not None


@pytest.mark.parametrize("path", ["/api/bd/interactions/99999", "/api/bd/interactions/x1"])
def test_delete_unknown_is_404(bd_seeded, bd_as_user, path):
    envelope(bd_as_user(EMERY).delete(path), 404, "not_found")


# ── the service, for other routers ───────────────────────────────────────────────────────────
def test_the_fallback_matches_bd_core():
    from bd import interactions_service as svc
    from test_bd_core_js import FALLBACK_CASES
    for cid, (outcome, text, today), due, action in FALLBACK_CASES:
        got = svc.fallback_next_action(outcome, text, today)
        assert got["due_date"].isoformat() == due, cid
        if action:
            assert got["action"] == action, cid
        assert got["source"] == "fallback"


def test_short_date():
    from bd import interactions_service as svc
    assert svc.short_date("2026-11-06") == "Fri, Nov 6"
    assert svc.short_date("2027-02-01") == "Mon, Feb 1"


def test_log_interaction_is_reusable_for_a_provider_call(bd_seeded, bd_db):
    from bd import interactions_service as svc
    out = svc.log_interaction(bd_db, 22, None, kind="call", outcome="answered",
                              occurred_at="2026-11-03T16:42:00-06:00", direction="in", duration_s=95,
                              summary="Caller asked about a quote.", provider="quo", external_id="AC990011",
                              recording_url="https://example.com/r.mp3", recommend=False)
    assert out["interaction"]["provider"] == "quo" and out["interaction"]["user_id"] is None
    assert out["interaction"]["counts_as_touch"] is True
    assert out["task"]["id"] == 304 and out["recommendation"] is None
    assert out["contact"]["last_live_at"] is not None and out["contact"]["cadence_status"] != "never"
    with pytest.raises(svc.InteractionInputError):
        svc.log_interaction(bd_db, 22, None, kind="call", outcome=None)


def test_is_touch_mirrors_the_generated_column():
    from bd import interactions_service as svc
    for kind, outcome, stored_kind, stored_outcome, touch in TOUCH_CASES:
        assert svc.is_touch(stored_kind, stored_outcome) is touch
        assert svc.normalize_kind(kind, outcome) == (stored_kind, stored_outcome)
