"""The Project Calendar: a read-only view of ONE Google calendar, the crews' job schedule.

Everything is exercised THROUGH THE HTTP API (GET /api/project-calendar) with a fake calendar
source standing in for Google, because the route is the contract the page is built against. The
claims that cost something when they are wrong:

  * ONE CALENDAR, EVER. The source is only asked for PROJECT_CALENDAR_ID; the real source only
    talks to the token endpoint and that calendar's events, never calendarList and never primary.
  * DATES ARE CENTRAL AND INCLUSIVE. Google's all-day end is exclusive; a late-evening job in
    Chicago is already "tomorrow" in UTC; weekends never count as workdays, DST or not.
  * RED IS A DURATION AND ITS LAST DAY IS THE DEADLINE. No other colour means anything.
  * A GOOGLE FAILURE NEVER 500s THE PAGE. The last good fetch is served stale; with none, an empty
    list and a plain error.

PUBLIC REPO: every project, person and calendar id below is made up.
"""
import copy
import json
import urllib.parse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

import main
import nav_access
import project_calendar as pc
import supabase_client

CAL_ID = "made-up-crew-schedule@group.calendar.example"
URL = "/api/project-calendar"


# ── fakes ─────────────────────────────────────────────────────────────────────
class FakeSource:
    """Stands in for Google: returns whatever events it holds, records what it was asked."""

    def __init__(self, events=None):
        self.events = list(events or [])
        self.calls = []
        self.fail = False

    def list_events(self, calendar_id, time_min, time_max):
        self.calls.append((calendar_id, time_min, time_max))
        if self.fail:
            raise RuntimeError("upstream unavailable")
        return copy.deepcopy(self.events)


class _DraftsQuery:
    def __init__(self, db):
        self.db = db
        self.filters = []

    def select(self, cols):
        self.db.selects.append(cols)
        self.cols = cols
        return self

    def is_(self, k, v):
        self.filters.append(("is", k, v)); return self

    def in_(self, k, vals):
        self.filters.append(("in", k, list(vals))); return self

    def execute(self):
        self.db.queries += 1
        if self.db.fail:
            raise RuntimeError("store down")
        out = []
        for r in self.db.rows:
            data = r.get("data") or {}
            ok = True
            for op, k, v in self.filters:
                if op == "is" and k == "deleted_at":
                    ok &= r.get("deleted_at") is None
                if op == "in" and k == "data->>job_number":
                    ok &= data.get("job_number") in v
            if ok:
                out.append({"id": r["id"], "created_at": r.get("created_at"),
                            "job_number": data.get("job_number"),
                            "project_name": data.get("project_name"),
                            "archived": None if data.get("archived") is None
                            else str(data.get("archived")).lower()})
        return type("R", (), {"data": out})()


class FakeDrafts:
    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.selects = []
        self.queries = 0
        self.fail = False

    def table(self, name):
        assert name == "drafts", name
        return _DraftsQuery(self)


# ── fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def drafts_db(monkeypatch):
    db = FakeDrafts()
    monkeypatch.setattr(supabase_client, "get_client", lambda: db)
    return db


@pytest.fixture
def source(monkeypatch, drafts_db):
    """A configured calendar backed by a fake source. TTL 0 unless a test says otherwise."""
    src = FakeSource()
    monkeypatch.setenv("PROJECT_CALENDAR_ID", CAL_ID)
    monkeypatch.setenv("PROJECT_CALENDAR_TTL_S", "0")
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON", raising=False)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_FILE", raising=False)
    monkeypatch.setattr(pc, "_make_source", lambda: src)
    return src


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pc.cache_clear()
    # The nav gate reads the caller's profile on every /api/* request; answer it without a store.
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": e, "role": "user", "status": "active"})
    main._profile_cache_clear()
    yield
    pc.cache_clear()


@pytest.fixture
def client():
    return TestClient(main.app)


def allday(eid, summary, start, end_excl, color=None, **extra):
    ev = {"id": eid, "summary": summary, "start": {"date": start}, "end": {"date": end_excl},
          "htmlLink": "https://calendar.example/event?eid=" + eid, **extra}
    if color is not None:
        ev["colorId"] = color
    return ev


def timed(eid, summary, start, end, color=None):
    ev = {"id": eid, "summary": summary, "start": {"dateTime": start}, "end": {"dateTime": end}}
    if color is not None:
        ev["colorId"] = color
    return ev


def get(client, start="2026-11-01", end="2026-11-30"):
    r = client.get(URL, params={"start": start, "end": end})
    assert r.status_code == 200, r.text
    return r.json()


def one(client, source, event, **rng):
    source.events = [event]
    body = get(client, **rng)
    assert len(body["events"]) == 1, body
    return body["events"][0]


# ── the contract's shape ──────────────────────────────────────────────────────
def test_the_response_has_every_contract_field(client, source):
    ev = one(client, source, allday("e1", "26.125, Acme Clinic Psych (6) (Pat)",
                                    "2026-11-09", "2026-11-12", "11"))
    body = get(client)
    assert set(body) == {"ok", "connected", "stale", "fetched_at", "error", "events"}
    assert body["ok"] is True and body["connected"] is True and body["stale"] is False
    assert body["error"] is None and body["fetched_at"].endswith("Z")
    assert set(ev) == {"id", "title", "name", "job_number", "crew_size", "mobilization",
                       "crew_lead", "is_punch", "prevailing_wage", "night_work", "color_id",
                       "color", "is_duration", "start", "last_day", "workdays", "deadline",
                       "project", "html_link"}
    assert ev["id"] == "e1"
    assert ev["title"] == "26.125, Acme Clinic Psych (6) (Pat)"
    assert ev["html_link"] == "https://calendar.example/event?eid=e1"


# ── title parsing ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("title,want", [
    ("26.125, Acme Clinic Psych (6) (Pat)",
     dict(name="Acme Clinic Psych", job_number="26.125", crew_size=6, mobilization=None,
          crew_lead="Pat", is_punch=False, prevailing_wage=False, night_work=False)),
    ("G25.110, The Example Lofts (3rd and 2nd) - 2nd Mob - (PW) (8) (Sam)",
     dict(name="The Example Lofts (3rd and 2nd)", job_number="G25.110", crew_size=8,
          mobilization=2, crew_lead="Sam", is_punch=False, prevailing_wage=True,
          night_work=False)),
    ("Example Diner (4)",
     dict(name="Example Diner", job_number=None, crew_size=4, mobilization=None, crew_lead=None,
          is_punch=False, prevailing_wage=False, night_work=False)),
    ("Example Plaza (6) - 2nd Mob",
     dict(name="Example Plaza", job_number=None, crew_size=6, mobilization=2, crew_lead=None,
          is_punch=False, prevailing_wage=False, night_work=False)),
    ("Example Punch - (1) (Lee)",
     dict(name="Example Punch", job_number=None, crew_size=1, mobilization=None, crew_lead="Lee",
          is_punch=True, prevailing_wage=False, night_work=False)),
    ("Example Shop (3) Night Work",
     dict(name="Example Shop", job_number=None, crew_size=3, mobilization=None, crew_lead=None,
          is_punch=False, prevailing_wage=False, night_work=True)),
    ("Example Patch?",
     dict(name="Example Patch?", job_number=None, crew_size=None, mobilization=None,
          crew_lead=None, is_punch=False, prevailing_wage=False, night_work=False)),
    ("Example Annex 1st Mob (5) (Kim)",
     dict(name="Example Annex", job_number=None, crew_size=5, mobilization=1, crew_lead="Kim",
          is_punch=False, prevailing_wage=False, night_work=False)),
    ("Example Depot 3rd Mob (2)",
     dict(name="Example Depot", job_number=None, crew_size=2, mobilization=3, crew_lead=None,
          is_punch=False, prevailing_wage=False, night_work=False)),
])
def test_each_title_shape_is_read(client, source, title, want):
    ev = one(client, source, allday("e1", title, "2026-11-09", "2026-11-10"))
    got = {k: ev[k] for k in want}
    assert got == want, title
    assert ev["title"] == title, "the raw title must come back untouched"


def test_the_last_bare_integer_is_the_crew_size(client, source):
    ev = one(client, source, allday("e1", "Example Hall (2) - (4) (Ann)", "2026-11-09", "2026-11-10"))
    assert ev["crew_size"] == 4 and ev["crew_lead"] == "Ann" and ev["name"] == "Example Hall"


def test_a_name_in_parentheses_that_is_not_last_is_not_a_crew_lead(client, source):
    ev = one(client, source, allday("e1", "Example Barn (Ann) (4)", "2026-11-09", "2026-11-10"))
    assert ev["crew_lead"] is None and ev["crew_size"] == 4
    assert ev["name"] == "Example Barn (Ann)", "what did not parse stays in the name"


def test_pw_and_numbers_are_never_a_crew_lead(client, source):
    assert one(client, source, allday("e1", "Example Yard (PW)", "2026-11-09", "2026-11-10")
               )["crew_lead"] is None
    assert one(client, source, allday("e1", "Example Yard (7)", "2026-11-09", "2026-11-10")
               )["crew_lead"] is None


@pytest.mark.parametrize("title", [None, "", "((((", "(", ")", "26.125,", "(3) (4) (5)",
                                   "Ünïcode Café (2) (Zoë)", "x" * 3000, "- - -", "(PW)"])
def test_parsing_never_throws_and_never_drops_an_event(client, source, title):
    ev = {"id": "e1", "start": {"date": "2026-11-09"}, "end": {"date": "2026-11-10"}}
    if title is not None:
        ev["summary"] = title
    got = one(client, source, ev)
    assert got["title"] == (title or "")
    assert isinstance(got["name"], str)


# ── dates ─────────────────────────────────────────────────────────────────────
def test_an_all_day_end_is_exclusive(client, source):
    """Google's end.date is the day AFTER the last day. Reading it as inclusive books a crew a day
    longer than the calendar shows, and moves every red Deadline a day late."""
    ev = one(client, source, allday("e1", "Example Diner (4)", "2026-11-09", "2026-11-12", "11"))
    assert ev["start"] == "2026-11-09" and ev["last_day"] == "2026-11-11"
    assert ev["deadline"] == "2026-11-11"
    assert ev["workdays"] == 3


def test_a_one_day_all_day_event_starts_and_ends_on_that_day(client, source):
    ev = one(client, source, allday("e1", "Example Diner (4)", "2026-11-09", "2026-11-10"))
    assert ev["start"] == ev["last_day"] == "2026-11-09"
    assert ev["workdays"] == 1


def test_a_timed_event_late_in_the_central_evening_lands_on_the_central_date(client, source):
    """9:30pm Central on the 12th is 03:30 UTC on the 13th. The calendar is Central."""
    ev = one(client, source, timed("e1", "Example Shop (3) Night Work",
                                   "2026-11-13T03:30:00Z", "2026-11-13T05:00:00Z"))
    assert ev["start"] == "2026-11-12" and ev["last_day"] == "2026-11-12"
    assert ev["night_work"] is True
    ev = one(client, source, timed("e2", "Example Shop (3)",
                                   "2026-11-12T21:30:00-06:00", "2026-11-12T23:30:00-06:00"))
    assert ev["start"] == ev["last_day"] == "2026-11-12"


def test_a_timed_overnight_shift_spans_both_central_days(client, source):
    ev = one(client, source, timed("e1", "Example Shop (3) Night Work",
                                   "2026-11-12T20:00:00-06:00", "2026-11-13T04:00:00-06:00"))
    assert (ev["start"], ev["last_day"], ev["workdays"]) == ("2026-11-12", "2026-11-13", 2)


def test_a_timed_event_ending_exactly_at_midnight_does_not_claim_the_next_day(client, source):
    ev = one(client, source, timed("e1", "Example Shop (3)",
                                   "2026-11-12T18:00:00-06:00", "2026-11-13T00:00:00-06:00"))
    assert ev["last_day"] == "2026-11-12"


def test_weekends_never_count_as_workdays(client, source):
    # Friday 13th to Monday 16th inclusive: Fri + Mon.
    ev = one(client, source, allday("e1", "Example Diner (4)", "2026-11-13", "2026-11-17"))
    assert ev["workdays"] == 2
    # Two full weeks, Monday to Sunday.
    ev = one(client, source, allday("e1", "Example Diner (4)", "2026-11-02", "2026-11-16"))
    assert ev["workdays"] == 10
    # A weekend on its own.
    ev = one(client, source, allday("e1", "Example Diner (4)", "2026-11-07", "2026-11-09"))
    assert ev["workdays"] == 0


def test_workdays_across_the_spring_dst_change(client, source):
    """Clocks go forward on Sunday 8 March 2026. Fri 6th to Tue 10th is Fri + Mon + Tue."""
    ev = one(client, source, allday("e1", "Example Diner (4)", "2026-03-06", "2026-03-11"),
             start="2026-03-01", end="2026-03-31")
    assert (ev["start"], ev["last_day"], ev["workdays"]) == ("2026-03-06", "2026-03-10", 3)


def test_a_timed_event_across_the_autumn_dst_change(client, source):
    """Clocks go back on Sunday 1 November 2026: the start is CDT (-05:00), the end CST (-06:00)."""
    ev = one(client, source, timed("e1", "Example Plaza (6) - 2nd Mob",
                                   "2026-10-30T08:00:00-05:00", "2026-11-02T17:00:00-06:00"),
             start="2026-10-25", end="2026-11-07")
    assert (ev["start"], ev["last_day"], ev["workdays"]) == ("2026-10-30", "2026-11-02", 2)


# ── colours and deadlines ─────────────────────────────────────────────────────
def test_red_is_a_duration_and_its_last_day_is_the_deadline(client, source):
    ev = one(client, source, allday("e1", "26.125, Acme Clinic Psych (6) (Pat)",
                                    "2026-11-09", "2026-11-21", "11"))
    assert ev["is_duration"] is True
    assert ev["color_id"] == "11" and ev["color"] == "#d50000"
    assert ev["deadline"] == ev["last_day"] == "2026-11-20"


@pytest.mark.parametrize("cid,hexval", [("1", "#7986cb"), ("2", "#33b679"), ("3", "#8e24aa"),
                                        ("4", "#e67c73"), ("5", "#f6bf26"), ("6", "#f4511e"),
                                        ("7", "#039be5"), ("8", "#616161"), ("9", "#3f51b5"),
                                        ("10", "#0b8043")])
def test_other_colours_are_shown_as_google_draws_them_and_carry_no_deadline(client, source, cid, hexval):
    ev = one(client, source, allday("e1", "Example Diner (4)", "2026-11-09", "2026-11-12", cid))
    assert ev["color"] == hexval and ev["color_id"] == cid
    assert ev["is_duration"] is False and ev["deadline"] is None


def test_no_colour_means_a_null_colour_and_no_deadline(client, source):
    ev = one(client, source, allday("e1", "Example Diner (4)", "2026-11-09", "2026-11-12"))
    assert ev["color_id"] is None and ev["color"] is None
    assert ev["is_duration"] is False and ev["deadline"] is None


# ── the range ─────────────────────────────────────────────────────────────────
def test_events_overlapping_the_range_are_returned_and_others_are_not(client, source):
    source.events = [
        allday("before", "Example Before (2)", "2026-11-02", "2026-11-05"),     # 2-4
        allday("leading", "Example Leading (2)", "2026-11-05", "2026-11-11"),   # 5-10
        allday("inside", "Example Inside (2)", "2026-11-11", "2026-11-12"),     # 11
        allday("on-end", "Example On End (2)", "2026-11-15", "2026-11-18"),     # 15-17
        allday("spanning", "Example Spanning (2)", "2026-11-01", "2026-11-30"),  # 1-29
        allday("after", "Example After (2)", "2026-11-16", "2026-11-18"),       # 16-17
        allday("touch-start", "Example Touch (2)", "2026-11-08", "2026-11-10"),  # 8-9
    ]
    body = get(client, "2026-11-09", "2026-11-15")
    assert sorted(e["id"] for e in body["events"]) == sorted(
        ["leading", "inside", "on-end", "spanning", "touch-start"])
    # Google is asked for the whole Central days of the range, end inclusive.
    assert source.calls[-1] == (CAL_ID, "2026-11-09T00:00:00-06:00", "2026-11-16T00:00:00-06:00")


def test_events_are_sorted_by_start_then_title(client, source):
    source.events = [
        allday("c", "Charlie (2)", "2026-11-10", "2026-11-11"),
        allday("b", "bravo (2)", "2026-11-09", "2026-11-10"),
        allday("a", "Alpha (2)", "2026-11-09", "2026-11-10"),
    ]
    assert [e["id"] for e in get(client)["events"]] == ["a", "b", "c"]


def test_a_cancelled_or_undated_event_is_left_out_without_breaking_the_rest(client, source):
    source.events = [
        allday("ok", "Example Diner (4)", "2026-11-09", "2026-11-10"),
        dict(allday("gone", "Example Gone (4)", "2026-11-09", "2026-11-10"), status="cancelled"),
        {"id": "nodate", "summary": "Example No Date"},
        {"id": "baddate", "summary": "Example Bad", "start": {"date": "soon"}, "end": {}},
    ]
    assert [e["id"] for e in get(client)["events"]] == ["ok"]


@pytest.mark.parametrize("params", [
    {},
    {"start": "2026-11-01"},
    {"end": "2026-11-30"},
    {"start": "11/01/2026", "end": "2026-11-30"},
    {"start": "2026-13-01", "end": "2026-12-30"},
    {"start": "2026-11-01", "end": "2026-11-31"},
    {"start": "2026-11-01T00:00", "end": "2026-11-30"},
    {"start": "2026-11-30", "end": "2026-11-01"},
    {"start": "2026-01-01", "end": "2026-05-01"},   # 121 days
])
def test_a_bad_range_is_a_400(client, source, params):
    r = client.get(URL, params=params)
    assert r.status_code == 400, (params, r.text)
    assert source.calls == [], "a bad range must not reach Google"


def test_a_120_day_range_is_allowed(client, source):
    assert client.get(URL, params={"start": "2026-01-01", "end": "2026-04-30"}).status_code == 200


# ── not connected ─────────────────────────────────────────────────────────────
def _unconfigure(monkeypatch):
    for k in ("PROJECT_CALENDAR_ID", "GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_SERVICE_ACCOUNT_FILE"):
        monkeypatch.delenv(k, raising=False)


def test_with_nothing_configured_the_api_says_not_connected(client, monkeypatch, drafts_db):
    _unconfigure(monkeypatch)
    body = get(client)
    assert body == {"ok": True, "connected": False, "stale": False, "fetched_at": None,
                    "error": None, "events": []}


def test_a_calendar_id_without_a_key_is_not_connected(client, monkeypatch, drafts_db):
    _unconfigure(monkeypatch)
    monkeypatch.setenv("PROJECT_CALENDAR_ID", CAL_ID)
    assert get(client)["connected"] is False


def test_a_key_without_a_calendar_id_is_not_connected_and_google_is_never_asked(client, monkeypatch):
    _unconfigure(monkeypatch)
    src = FakeSource([allday("e1", "Example Diner (4)", "2026-11-09", "2026-11-10")])
    monkeypatch.setattr(pc, "_make_source", lambda: src)
    assert get(client)["connected"] is False
    assert src.calls == []


def test_an_unreadable_key_is_not_connected(client, monkeypatch, tmp_path):
    _unconfigure(monkeypatch)
    monkeypatch.setenv("PROJECT_CALENDAR_ID", CAL_ID)
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", "{not json")
    assert get(client)["connected"] is False
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(tmp_path / "missing.json"))
    assert get(client)["connected"] is False


def test_the_key_is_read_from_the_json_text_or_from_a_file(monkeypatch, tmp_path):
    _unconfigure(monkeypatch)
    key = {"client_email": "reader@made-up.iam.example", "private_key": _PEM,
           "private_key_id": "k1"}
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_JSON", json.dumps(key))
    assert isinstance(pc._make_source(), pc.ServiceAccountSource)
    monkeypatch.delenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    path = tmp_path / "key.json"
    path.write_text(json.dumps(key), encoding="utf-8")
    monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_FILE", str(path))
    assert isinstance(pc._make_source(), pc.ServiceAccountSource)


# ── caching and failure ───────────────────────────────────────────────────────
def test_a_range_is_reused_within_the_ttl(client, source, monkeypatch):
    monkeypatch.setenv("PROJECT_CALENDAR_TTL_S", "300")
    source.events = [allday("e1", "Example Diner (4)", "2026-11-09", "2026-11-10")]
    first = get(client)
    second = get(client)
    assert len(source.calls) == 1
    assert first["fetched_at"] == second["fetched_at"] and second["stale"] is False
    get(client, "2026-12-01", "2026-12-31")
    assert len(source.calls) == 2, "a different range is a different fetch"


def test_a_google_failure_after_a_good_fetch_serves_the_old_events_as_stale(client, source):
    source.events = [allday("e1", "26.125, Acme Clinic Psych (6) (Pat)",
                            "2026-11-09", "2026-11-12", "11")]
    good = get(client)
    source.fail = True
    source.events = []
    body = get(client)
    assert body["ok"] is True and body["connected"] is True
    assert body["stale"] is True
    assert body["events"] == good["events"]
    assert body["fetched_at"] == good["fetched_at"], "stale data must say when it was fetched"
    assert body["error"]
    source.fail = False
    assert get(client)["stale"] is False


def test_a_google_failure_with_nothing_cached_is_an_empty_list_not_a_500(client, source):
    source.fail = True
    r = client.get(URL, params={"start": "2026-11-01", "end": "2026-11-30"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["connected"] is True and body["stale"] is False
    assert body["events"] == [] and body["fetched_at"] is None
    assert isinstance(body["error"], str) and body["error"]
    assert "upstream unavailable" not in body["error"], "the message is plain, not the exception"


def test_stale_results_are_kept_per_range(client, source):
    source.events = [allday("e1", "Example Diner (4)", "2026-11-09", "2026-11-10")]
    get(client, "2026-11-01", "2026-11-30")
    source.fail = True
    other = get(client, "2026-12-01", "2026-12-31")
    assert other["events"] == [] and other["stale"] is False and other["error"]


# ── one calendar, ever ────────────────────────────────────────────────────────
def test_the_source_is_only_ever_asked_for_the_configured_calendar(client, source):
    source.events = [allday("e1", "Example Diner (4)", "2026-11-09", "2026-11-10")]
    for rng in (("2026-11-01", "2026-11-30"), ("2026-10-01", "2026-10-31"),
                ("2026-11-09", "2026-11-09")):
        get(client, *rng)
    client.get(URL, params={"start": "2026-11-01", "end": "2026-11-30",
                            "calendar_id": "primary", "calendarId": "someone-else@example"})
    assert source.calls and {c[0] for c in source.calls} == {CAL_ID}


def _make_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return pem, pub


_PEM, _PUB = _make_pem()


class FakeGoogle:
    """An httpx MockTransport handler playing Google's token endpoint and events.list."""

    def __init__(self, pages):
        self.pages = pages
        self.requests = []
        self.events_status = 200

    def __call__(self, request):
        self.requests.append(request)
        if request.url.host == "oauth2.googleapis.com" and request.url.path == "/token":
            form = urllib.parse.parse_qs(request.content.decode())
            self.assertion = form["assertion"][0]
            self.grant = form["grant_type"][0]
            return httpx.Response(200, json={"access_token": "made-up-token", "expires_in": 3600})
        if request.url.host == "www.googleapis.com":
            if self.events_status != 200:
                return httpx.Response(self.events_status, json={"error": "nope"})
            tok = request.url.params.get("pageToken")
            idx = int(tok) if tok else 0
            body = {"items": self.pages[idx]}
            if idx + 1 < len(self.pages):
                body["nextPageToken"] = str(idx + 1)
            return httpx.Response(200, json=body)
        return httpx.Response(404)


@pytest.fixture
def google(monkeypatch, drafts_db):
    _unconfigure(monkeypatch)
    monkeypatch.setenv("PROJECT_CALENDAR_ID", CAL_ID)
    monkeypatch.setenv("PROJECT_CALENDAR_TTL_S", "0")
    fake = FakeGoogle([[allday("p1", "Example Diner (4)", "2026-11-09", "2026-11-10")],
                       [allday("p2", "Example Plaza (6) - 2nd Mob", "2026-11-10", "2026-11-12", "11")]])
    src = pc.ServiceAccountSource({"client_email": "reader@made-up.iam.example",
                                   "private_key": _PEM}, transport=httpx.MockTransport(fake))
    monkeypatch.setattr(pc, "_make_source", lambda: src)
    return fake


def test_the_real_source_reads_only_that_calendars_events_read_only(client, google):
    body = get(client)
    get(client)
    assert [e["id"] for e in body["events"]] == ["p1", "p2"], "pagination was not followed"
    calls = [r for r in google.requests if r.url.host == "www.googleapis.com"]
    want = "/calendar/v3/calendars/%s/events" % urllib.parse.quote(CAL_ID, safe="")
    assert calls and all(r.url.raw_path.decode().split("?")[0] == want for r in calls)
    assert all(r.method == "GET" for r in calls), "the calendar is never written"
    for r in google.requests:
        assert "calendarList" not in str(r.url) and "/primary" not in str(r.url)
    p = calls[0].url.params
    assert (p["singleEvents"], p["orderBy"], p["timeZone"]) == ("true", "startTime", "America/Chicago")
    # Midnight on 1 November is still CDT (the clocks go back at 2am); 1 December is CST.
    assert p["timeMin"] == "2026-11-01T00:00:00-05:00" and p["timeMax"] == "2026-12-01T00:00:00-06:00"
    assert calls[0].headers["authorization"] == "Bearer made-up-token"


def test_the_token_is_a_read_only_jwt_bearer_grant_and_is_cached(client, google):
    get(client)
    get(client)
    tokens = [r for r in google.requests if r.url.host == "oauth2.googleapis.com"]
    assert len(tokens) == 1, "the access token was minted again before it expired"
    assert google.grant == "urn:ietf:params:oauth:grant-type:jwt-bearer"
    claims = jwt.decode(google.assertion, _PUB, algorithms=["RS256"],
                        audience="https://oauth2.googleapis.com/token")
    assert claims["scope"] == "https://www.googleapis.com/auth/calendar.events.readonly"
    assert claims["iss"] == "reader@made-up.iam.example"


def test_the_real_source_stops_at_its_page_cap(client, google, monkeypatch):
    monkeypatch.setattr(pc, "_PAGE_CAP", 3)
    google.pages = [[allday("p%d" % i, "Example %d (2)" % i, "2026-11-09", "2026-11-10")]
                    for i in range(10)]
    body = get(client)
    assert len(body["events"]) == 3
    assert len([r for r in google.requests if r.url.host == "www.googleapis.com"]) == 3


def test_a_google_error_status_never_logs_the_key_or_the_token(client, google, caplog):
    google.events_status = 403
    with caplog.at_level("DEBUG"):
        body = get(client)
    assert body["events"] == [] and body["error"]
    text = caplog.text
    assert "made-up-token" not in text
    assert "PRIVATE KEY" not in text and _PEM.splitlines()[1] not in text


# ── project matching ──────────────────────────────────────────────────────────
def test_an_event_links_to_the_tool_project_with_its_job_number(client, source, drafts_db):
    drafts_db.rows = [
        {"id": "d-old-archived", "created_at": "2026-01-01", "deleted_at": None,
         "data": {"job_number": "26.125", "project_name": "Acme Clinic (archived copy)",
                  "archived": True}},
        {"id": "d-home", "created_at": "2026-02-01", "deleted_at": None,
         "data": {"job_number": "26.125", "project_name": "Acme Clinic Psych"}},
        {"id": "d-later", "created_at": "2026-03-01", "deleted_at": None,
         "data": {"job_number": "26.125", "project_name": "Acme Clinic Psych - Scope 2"}},
        {"id": "d-deleted", "created_at": "2025-01-01", "deleted_at": "2026-05-01",
         "data": {"job_number": "G25.110", "project_name": "Deleted Lofts"}},
        {"id": "d-other", "created_at": "2026-01-01", "deleted_at": None,
         "data": {"job_number": "99.999", "project_name": "Unrelated"}},
    ]
    source.events = [
        allday("a", "26.125, Acme Clinic Psych (6) (Pat)", "2026-11-09", "2026-11-10"),
        allday("b", "26.125, Acme Clinic Psych - 2nd Mob (6) (Pat)", "2026-11-16", "2026-11-17"),
        allday("c", "G25.110, The Example Lofts (8) (Sam)", "2026-11-09", "2026-11-10"),
        allday("d", "Example Diner (4)", "2026-11-09", "2026-11-10"),
    ]
    by_id = {e["id"]: e for e in get(client)["events"]}
    assert by_id["a"]["project"] == {"id": "d-home", "name": "Acme Clinic Psych"}
    assert by_id["b"]["project"] == {"id": "d-home", "name": "Acme Clinic Psych"}
    assert by_id["c"]["project"] is None, "a deleted draft is not a project"
    assert by_id["d"]["project"] is None
    assert drafts_db.queries == 1, "one query per request, not one per event"
    cols = drafts_db.selects[0]
    assert "data->>job_number" in cols, cols
    assert not any(c.strip() == "data" for c in cols.split(",")), "the whole blob was fetched"


def test_no_job_numbers_means_no_query(client, source, drafts_db):
    source.events = [allday("d", "Example Diner (4)", "2026-11-09", "2026-11-10")]
    get(client)
    assert drafts_db.queries == 0


def test_a_failed_project_lookup_leaves_project_null_and_the_calendar_up(client, source, drafts_db):
    drafts_db.fail = True
    source.events = [allday("a", "26.125, Acme Clinic Psych (6) (Pat)", "2026-11-09", "2026-11-10")]
    body = get(client)
    assert body["events"][0]["project"] is None and body["error"] is None


def test_a_project_saved_after_the_fetch_appears_without_waiting_for_the_cache(
        client, source, drafts_db, monkeypatch):
    monkeypatch.setenv("PROJECT_CALENDAR_TTL_S", "300")
    source.events = [allday("a", "26.125, Acme Clinic Psych (6) (Pat)", "2026-11-09", "2026-11-10")]
    assert get(client)["events"][0]["project"] is None
    drafts_db.rows = [{"id": "d1", "created_at": "2026-02-01", "deleted_at": None,
                       "data": {"job_number": "26.125", "project_name": "Acme Clinic Psych"}}]
    assert get(client)["events"][0]["project"] == {"id": "d1", "name": "Acme Clinic Psych"}
    assert len(source.calls) == 1


# ── the sidebar row ───────────────────────────────────────────────────────────
@pytest.fixture
def nav_file(tmp_path, monkeypatch):
    monkeypatch.setattr(nav_access, "_FILE", tmp_path / "nav_access.json")
    monkeypatch.setattr(nav_access, "_DATA_DIR", tmp_path)


def test_the_row_is_keyed_on_its_href_and_owns_its_page(nav_file):
    tab = nav_access.TABS["/project-calendar.html"]
    assert tab["label"] == "Project Calendar"
    assert tab["pages"] == ("/project-calendar.html",)
    assert "/project-calendar.html" not in nav_access.LOCKED


def test_a_denied_role_is_refused_the_page_and_told_so_by_api_me(client, source, nav_file):
    nav_access.save({"user": ["/project-calendar.html"]}, "admin@made-up.example")
    assert nav_access.page_denied("user", "/project-calendar.html") == "/project-calendar.html"
    assert nav_access.page_denied("admin", "/project-calendar.html") is None
    me = client.get("/api/me").json()
    assert "/project-calendar.html" in me["nav_denied"]
    assert me["nav_denied_pages"].get("/project-calendar.html") == "/project-calendar.html"
    # Hide-only since 2026-10-27, like every tab: the route still answers.
    assert client.get(URL, params={"start": "2026-11-01", "end": "2026-11-30"}).status_code == 200


def test_if_tabs_are_sealed_again_the_route_is_refused_to_a_denied_role_only(
        client, source, nav_file, monkeypatch):
    """The single-caller route the row's note names. Put back for one test, the middleware 403s a
    denied member and lets an admin through."""
    monkeypatch.setitem(nav_access.TABS, "/project-calendar.html",
                        {**nav_access.TABS["/project-calendar.html"], "api": ("/api/project-calendar",)})
    nav_access.save({"user": ["/project-calendar.html"]}, "admin@made-up.example")
    r = client.get(URL, params={"start": "2026-11-01", "end": "2026-11-30"})
    assert r.status_code == 403 and r.json()["nav_denied"] is True
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: {"id": "u2", "email": e, "role": "admin", "status": "active"})
    main._profile_cache_clear()
    assert client.get(URL, params={"start": "2026-11-01", "end": "2026-11-30"}).status_code == 200


# ── review fixes ──────────────────────────────────────────────────────────────
def test_a_parenthesised_punch_is_a_punch_not_a_crew_lead(client, source):
    ev = one(client, source, allday("e1", "Example Hall (Punch)", "2026-11-09", "2026-11-10"))
    assert ev["is_punch"] is True
    assert ev["crew_lead"] is None, "the word Punch marks a Punch, never a person"


def test_after_a_google_failure_google_is_left_alone_for_a_while(client, google):
    """A failing Google must not be called on every request: answer from the cache or the plain
    error during the backoff, then try again once it has passed."""
    google.events_status = 503
    assert get(client)["error"]
    calls = len([r for r in google.requests if r.url.host == "www.googleapis.com"])
    google.events_status = 200
    body = get(client)
    assert body["error"], "during the backoff the API still reports the failure"
    assert len([r for r in google.requests if r.url.host == "www.googleapis.com"]) == calls, \
        "Google was called again during the backoff"
    pc._make_source()._backoff_until = 0.0        # the backoff has passed
    assert [e["id"] for e in get(client)["events"]] == ["p1", "p2"]


def test_concurrent_requests_mint_one_token_and_none_waits_on_a_held_lock(google):
    """The token is minted by one request while the others wait for it and reuse it; the state
    lock is never held across the network call."""
    import threading
    import time as _t

    slow = google.__call__

    def handler(request):
        if request.url.host == "oauth2.googleapis.com":
            _t.sleep(0.3)
        return slow(request)

    src = pc._make_source()
    src._transport = httpx.MockTransport(handler)
    results, errors = [], []

    def worker():
        try:
            results.append(src.list_events(CAL_ID, "2026-11-01T00:00:00-05:00",
                                           "2026-12-01T00:00:00-06:00"))
        except Exception as exc:  # pragma: no cover - surfaced by the assert below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    _t.sleep(0.1)
    assert src._lock.acquire(timeout=0.05), "the state lock is held across the token request"
    src._lock.release()
    for t in threads:
        t.join(5)
    assert not errors and len(results) == 4
    assert len([r for r in google.requests if r.url.host == "oauth2.googleapis.com"]) == 1
