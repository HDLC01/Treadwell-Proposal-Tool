"""Plan vs Actual, the Raken side (#782): days clocked in, people on site, Actual hours, Behind,
Not linked, and the Raken-only section.

Exercised THROUGH THE HTTP API (GET /api/project-analytics and POST /api/project-analytics/refresh)
with a fake Google calendar (test_plan_vs_actual's) and a fake Raken behind an httpx.MockTransport,
answering in the shapes Raken's API docs give: a {"page": {..."nextOffset": "10"}, "collection":
[...]} envelope (nextOffset a STRING, as in the docs' example), projects carrying "number", time
cards carrying "date", "totalHours", "worker": {"uuid"} and "project": {"uuid"}. The claims that
cost something when they are wrong:

  * A Raken project links when its Project Number, trimmed, equals the Job number EXACTLY; two with
    the same number make the job Not linked, naming both; a Not linked job has no other status.
  * Time cards only, approved and unapproved, read page by page in pieces of at most 31 days up to
    YESTERDAY, never filtered by project. A Punch's hours count toward its parent.
  * Days clocked in = booked Workdays so far with any hours; average on site = distinct workers on
    each of those days, added up, divided by the days; Behind = days clocked in < Workdays booked.
  * GET never calls Raken; "Refresh now" does, keeps its result on the data volume (a restart keeps
    it), and a second refresh while one runs waits for it instead of reading Raken again.
  * Raken not connected, expired, not turned on or unreachable: the calendar side still shows, every
    row says which, and the page has one plain message. Never a 500.

"Today" is Wednesday 2026-11-18 (Central), so "so far" runs through Tuesday 2026-11-17. PUBLIC REPO:
every job, person, project, number and id below is made up.
"""
import datetime as dt
import threading
import time
import urllib.parse

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

import main
import plan_vs_actual
import project_calendar as pc
import raken
import raken_actuals
import supabase_client
from test_plan_vs_actual import CAL_ID, TODAY, FakeDrafts, FakeGoogle, mob

URL = "/api/project-analytics"
REFRESH = "/api/project-analytics/refresh"
KEY = Fernet.generate_key().decode()
CLIENT_ID = "made-up-raken-client"
CLIENT_SECRET = "made-up-raken-secret-value"
SEED_REFRESH = "made-up-refresh-seed"


# ── the fake Raken ────────────────────────────────────────────────────────────
class FakeRaken:
    """Raken's token endpoint, GET /projects and GET /timeCards, in the documented shapes."""

    def __init__(self):
        self.lock = threading.Lock()
        self.n = 0
        self.valid_refresh = {SEED_REFRESH}
        self.valid_access = set()
        self.projects = []
        self.cards = []
        self.page_size = 100
        self.project_calls = 0
        self.card_calls = []            # (fromDate, toDate, offset) of every /timeCards call
        self.card_params = []           # the full query of every /timeCards call
        self.refuse = None              # a JSON body: answer every data call 403 with it
        self.down = False               # every data call fails to connect
        self.card_delay = 0.0
        self.gate = None                # a threading.Event every /timeCards call waits on
        self.entered = threading.Event()  # set once a /timeCards call has arrived
        self.project_params = []        # the "statuses" asked for on every /projects call
        self.projects_next = None       # a nextOffset to send on every /projects page instead
        self.in_flight = 0
        self.max_in_flight = 0
        # GET /projects/{uuid}/productionInsights (#783): each project's divisions, in the docs'
        # shape. A project not in `insights` has no Raken budget: an empty collection.
        self.insights = {}
        self.insight_calls = []         # (project uuid, the full query) of every call
        self.insight_fail = set()       # project uuids whose insights answer 500

    def handle(self, request):
        with self.lock:
            self.in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            return self._handle(request)
        finally:
            with self.lock:
                self.in_flight -= 1

    def _page(self, items, url):
        offset = int(url.params.get("offset", "0"))
        limit = min(int(url.params.get("limit", "10")), self.page_size)
        chunk = items[offset:offset + limit]
        nxt = offset + limit if offset + limit < len(items) else None
        return httpx.Response(200, json={
            "page": {"offset": offset, "limit": limit, "totalElements": len(items),
                     "previous": None, "next": None if nxt is None else "made-up-next",
                     "nextOffset": None if nxt is None else str(nxt)},
            "collection": chunk})

    def _handle(self, request):
        url = request.url
        if url.host == "app.rakenapp.com" and url.path == "/oauth/token":
            form = dict(urllib.parse.parse_qsl(request.content.decode()))
            sent = form.get("refresh_token")
            with self.lock:
                if form.get("grant_type") != "refresh_token" or sent not in self.valid_refresh:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                self.valid_refresh.discard(sent)
                self.n += 1
                access, refresh = "made-up-access-%d" % self.n, "made-up-refresh-%d" % self.n
                self.valid_access.add(access)
                self.valid_refresh.add(refresh)
            return httpx.Response(200, json={"access_token": access, "refresh_token": refresh,
                                             "token_type": "bearer", "expires_in": 36000})
        if url.host != "developer.rakenapp.com":
            return httpx.Response(404)
        if self.down:
            raise httpx.ConnectError("made-up connection failure")
        auth = request.headers.get("authorization", "")
        if auth[7:] not in self.valid_access:
            return httpx.Response(401, json={"message": "Unauthorized"})
        if self.refuse is not None:
            return httpx.Response(403, json=self.refuse)
        if url.path == "/api/projects":
            self.project_calls += 1
            self.project_params.append(url.params.get_list("statuses"))
            resp = self._page(self.projects, url)
            if self.projects_next is not None:
                body = resp.json()
                body["page"]["nextOffset"] = self.projects_next
                resp = httpx.Response(200, json=body)
            return resp
        if url.path == "/api/timeCards":
            q = dict(url.params)
            self.card_params.append(q)
            a, b = q["fromDate"], q["toDate"]
            if (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days > 31 or a > b:
                return httpx.Response(400, json={"message": "made-up range refusal"})
            self.card_calls.append((a, b, int(q.get("offset", "0"))))
            self.entered.set()
            if self.gate is not None:
                self.gate.wait(10)
            if self.card_delay:
                time.sleep(self.card_delay)
            hits = [c for c in self.cards if a <= c["date"] <= b]
            if q.get("projectUuid"):
                hits = [c for c in hits if c["project"]["uuid"] == q["projectUuid"]]
            return self._page(hits, url)
        parts = url.path.split("/")
        if len(parts) == 5 and parts[:3] == ["", "api", "projects"] \
                and parts[4] == "productionInsights":
            uuid = parts[3]
            self.insight_calls.append((uuid, dict(url.params)))
            if uuid in self.insight_fail:
                return httpx.Response(500, json={"message": "made-up insights failure"})
            return self._page(self.insights.get(uuid, []), url)
        return httpx.Response(404, json={"message": "not in the fake"})

    def windows(self):
        """The distinct (fromDate, toDate) pieces asked for, in order."""
        out = []
        for a, b, _o in self.card_calls:
            if (a, b) not in out:
                out.append((a, b))
        return out


def project(uuid, number, name):
    return {"uuid": uuid, "name": name, "number": number, "status": "ACTIVE"}


_CARD_N = [0]


def card(project_uuid, day, worker, hours, approved=True, **extra):
    _CARD_N[0] += 1
    c = {"uuid": "made-up-card-%d" % _CARD_N[0], "workLogUuid": None, "date": day,
         "totalHours": hours, "approved": approved, "worker": {"uuid": worker},
         "project": {"uuid": project_uuid}, "deletedAt": None,
         "timeEntries": [{"hours": hours, "payType": None}]}
    c.update(extra)
    return c


# ── fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def google(monkeypatch):
    src = FakeGoogle()
    db = FakeDrafts()
    monkeypatch.setattr(supabase_client, "get_client", lambda: db)
    monkeypatch.setenv("PROJECT_CALENDAR_ID", CAL_ID)
    monkeypatch.setenv("PROJECT_CALENDAR_TTL_S", "0")
    monkeypatch.setattr(pc, "_make_source", lambda: src)
    monkeypatch.setattr(pc, "today_central", lambda: TODAY)
    return src


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """A Raken the tool is signed in to, and an empty data folder."""
    f = FakeRaken()
    monkeypatch.setenv("RAKEN_CLIENT_ID", CLIENT_ID)
    monkeypatch.setenv("RAKEN_CLIENT_SECRET", CLIENT_SECRET)
    monkeypatch.setenv("RAKEN_REDIRECT_URI", "https://tool.example.test/api/raken/callback")
    monkeypatch.setenv("RAKEN_TOKEN_KEY", KEY)
    monkeypatch.setattr(raken, "TOKEN_FILE", tmp_path / "raken_signin.json")
    monkeypatch.setattr(raken_actuals, "STORE_FILE", tmp_path / "raken_actuals.json")
    monkeypatch.setattr(raken, "TRANSPORT", httpx.MockTransport(f.handle))
    monkeypatch.setattr(raken, "sleep", lambda s: None)
    monkeypatch.setattr(raken_actuals, "now_utc",
                        lambda: dt.datetime(2026, 11, 18, 15, 5, tzinfo=dt.timezone.utc))
    raken.reset_for_tests()
    raken_actuals.reset_for_tests()
    raken._write_file(SEED_REFRESH)
    yield f
    raken.reset_for_tests()
    raken_actuals.reset_for_tests()


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    pc.cache_clear()
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": e, "role": "user", "status": "active"})
    main._profile_cache_clear()
    yield
    pc.cache_clear()


@pytest.fixture
def client():
    return TestClient(main.app, raise_server_exceptions=False)


def get(client):
    r = client.get(URL)
    assert r.status_code == 200, r.text
    return r.json()


def refresh(client):
    r = client.post(REFRESH)
    assert r.status_code == 200, r.text
    return r.json()


def by_key(body):
    return {p["key"]: p for p in body["projects"]}


# A five-day job running this week: Mon Nov 16 to Fri Nov 20, three people. Booked so far: Mon, Tue.
JOB = mob("j", "26.501, Example Clinic (3) (Pat)", "2026-11-16", "2026-11-20", "11")


# ── linking ───────────────────────────────────────────────────────────────────
def test_a_job_links_to_the_raken_project_whose_number_trimmed_equals_its_job_number(
        client, google, fake):
    google.events = [JOB]
    fake.projects = [project("r-1", " 26.501 ", "Example Clinic"),
                     project("r-2", "26.5011", "Example Clinic Annex"),
                     project("r-3", "X26.501", "Example Other")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-16", "w-2", 8),
                  card("r-1", "2026-11-17", "w-1", 8), card("r-1", "2026-11-17", "w-2", 8),
                  card("r-1", "2026-11-17", "w-3", 6.5, approved=False),
                  card("r-2", "2026-11-17", "w-9", 8)]
    body = refresh(client)
    p = by_key(body)["job:26.501"]
    r = p["raken"]
    assert r["state"] == "linked"
    assert [x["uuid"] for x in r["projects"]] == ["r-1"]
    assert r["days_booked"] == 2 and r["days_clocked"] == 2
    assert r["avg_on_site"] == 2.5, "2 people Monday, 3 Tuesday"
    assert r["actual_hours"] == 38.5, "approved and unapproved cards both count"
    assert p["statuses"] == ["on_plan"], "linked, not Behind, no Raken budget (#783)"
    # The calendar side is untouched.
    assert p["workdays_so_far"] == 2 and p["planned_hours"] == 2 * 3 * 8


def test_get_never_calls_raken_and_serves_the_last_refresh(client, google, fake):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    before = get(client)
    assert fake.project_calls == 0 and fake.card_calls == []
    assert before["raken"]["state"] == "not_refreshed"
    assert before["raken"]["as_of"] is None
    assert by_key(before)["job:26.501"]["raken"]["state"] == "not_refreshed"
    refresh(client)
    calls = (fake.project_calls, len(fake.card_calls))
    after = get(client)
    assert (fake.project_calls, len(fake.card_calls)) == calls, "GET read Raken"
    assert after["raken"]["state"] == "connected"
    assert after["raken"]["as_of"] == "2026-11-18T09:05:00-06:00", "the as-of time is Central"
    assert after["raken"]["through"] == "2026-11-17"
    assert by_key(after)["job:26.501"]["raken"]["actual_hours"] == 8


def test_a_job_with_no_raken_project_or_no_job_number_is_not_linked_and_nothing_else(
        client, google, fake):
    google.events = [mob("a", "26.502, Example Depot (2)", "2026-11-16", "2026-11-20"),
                     mob("b", "Example Diner (4)", "2026-11-16", "2026-11-20")]
    fake.projects = [project("r-1", "26.999", "Example Elsewhere")]
    body = refresh(client)
    rows = by_key(body)
    a, b = rows["job:26.502"], rows["name:examplediner"]
    assert a["raken"]["state"] == "not_linked" and a["raken"]["reason"] == "no_raken_project"
    assert b["raken"]["state"] == "not_linked" and b["raken"]["reason"] == "no_job_number"
    # Nobody clocked in on two booked days, yet a Not linked job is never also Behind.
    assert a["statuses"] == ["not_linked"] and b["statuses"] == ["not_linked"]
    assert "days_clocked" not in a["raken"]


def test_two_raken_projects_with_the_job_number_make_it_not_linked_naming_both(
        client, google, fake):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic"),
                     project("r-2", "26.501 ", "Example Clinic Copy")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    p = by_key(refresh(client))["job:26.501"]
    assert p["raken"]["state"] == "not_linked" and p["raken"]["reason"] == "duplicate"
    assert sorted(d["name"] for d in p["raken"]["duplicates"]) == [
        "Example Clinic", "Example Clinic Copy"]
    assert p["statuses"] == ["not_linked"]


# ── Punches ───────────────────────────────────────────────────────────────────
def test_a_punchs_hours_count_toward_its_parent(client, google, fake):
    """The job ran Mon Nov 2 to Fri Nov 6; its Punch (Thu Nov 12) carries another Job number but
    joins it by name. Hours on the Punch's own Raken project count toward the job, and that project
    is not listed as Raken-only."""
    google.events = [mob("m", "26.125, Acme Clinic Psych (2) (Pat)", "2026-11-02", "2026-11-06"),
                     mob("p", "26.912, Acme Clinic Psych Punch (1) (Lee)", "2026-11-12",
                         "2026-11-12")]
    fake.projects = [project("r-1", "26.125", "Acme Clinic Psych"),
                     project("r-2", "26.912", "Acme Clinic Psych Punch")]
    fake.cards = [card("r-1", day, w, 8) for day in ("2026-11-02", "2026-11-03", "2026-11-04",
                                                       "2026-11-05", "2026-11-06")
                  for w in ("w-1", "w-2")] + [card("r-2", "2026-11-12", "w-3", 4)]
    body = refresh(client)
    (p,) = body["projects"]
    r = p["raken"]
    assert r["state"] == "linked"
    assert r["days_booked"] == 6 and r["days_clocked"] == 6
    assert r["actual_hours"] == 5 * 2 * 8 + 4
    assert r["avg_on_site"] == round((5 * 2 + 1) / 6, 1)
    assert p["statuses"] == ["on_plan"]
    assert body["raken_only"] == []


# ── the figures ───────────────────────────────────────────────────────────────
def test_average_on_site_counts_each_days_distinct_workers(client, google, fake):
    """Mon: w-1, w-2. Tue: w-2, w-3 (w-3 with two cards). Wed Nov 11: w-3, w-4, w-5. (2+2+3)/3."""
    google.events = [mob("j", "26.510, Example Hall (3)", "2026-11-09", "2026-11-11")]
    fake.projects = [project("r-1", "26.510", "Example Hall")]
    fake.cards = [card("r-1", "2026-11-09", "w-1", 8), card("r-1", "2026-11-09", "w-2", 8),
                  card("r-1", "2026-11-10", "w-2", 8), card("r-1", "2026-11-10", "w-3", 4),
                  card("r-1", "2026-11-10", "w-3", 4), card("r-1", "2026-11-11", "w-3", 8),
                  card("r-1", "2026-11-11", "w-4", 8), card("r-1", "2026-11-11", "w-5", 8)]
    r = by_key(refresh(client))["job:26.510"]["raken"]
    assert r["days_clocked"] == 3
    assert r["avg_on_site"] == 2.3
    assert r["actual_hours"] == 56


def test_a_missed_booked_day_makes_the_job_behind(client, google, fake):
    """Booked Mon and Tue; crews clocked in Monday and on Saturday (not a Workday) only."""
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-14", "w-1", 5)]
    p = by_key(refresh(client))["job:26.501"]
    r = p["raken"]
    assert r["days_booked"] == 2 and r["days_clocked"] == 1
    assert r["actual_hours"] == 13, "Saturday's hours are still Actual hours"
    assert r["avg_on_site"] == 1
    assert p["statuses"] == ["behind"]


def test_todays_cards_are_never_counted(client, google, fake):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-17", "w-1", 8),
                  card("r-1", "2026-11-18", "w-1", 8)]
    refresh(client)
    assert max(b for _a, b, _o in fake.card_calls) == "2026-11-17", "read up to yesterday"


def test_a_deleted_card_is_not_counted(client, google, fake):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-17", "w-1", 8),
                  card("r-1", "2026-11-17", "w-2", 8, deletedAt="2026-11-17T20:00:00Z")]
    r = by_key(refresh(client))["job:26.501"]["raken"]
    assert r["actual_hours"] == 16 and r["avg_on_site"] == 1


# ── reading: pieces, paging, no project filter ────────────────────────────────
def test_a_long_job_is_read_in_pieces_of_at_most_31_days_with_no_project_filter(
        client, google, fake):
    """The job started Tue Sep 1: time cards are read from Sep 1 to yesterday, in back-to-back
    pieces no longer than Raken allows, never filtered by project."""
    google.events = [mob("j", "26.520, Example Warehouse (2)", "2026-09-01", "2026-11-20")]
    fake.projects = [project("r-1", "26.520", "Example Warehouse")]
    fake.cards = [card("r-1", "2026-09-01", "w-1", 8), card("r-1", "2026-10-01", "w-1", 8),
                  card("r-1", "2026-10-02", "w-1", 8), card("r-1", "2026-11-17", "w-1", 8)]
    r = by_key(refresh(client))["job:26.520"]["raken"]
    wins = fake.windows()
    assert len(wins) >= 3
    assert wins[0][0] <= "2026-09-01" and wins[-1][1] == "2026-11-17"
    for (a1, b1), (a2, _b2) in zip(wins, wins[1:]):
        assert dt.date.fromisoformat(a2) == dt.date.fromisoformat(b1) + dt.timedelta(days=1)
    for a, b in wins:
        assert (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days <= 30
    assert all("projectUuid" not in q and "projectUuids" not in q for q in fake.card_params)
    assert r["actual_hours"] == 32 and r["days_clocked"] == 4


def test_the_read_goes_back_at_most_365_days(client, google, fake):
    google.events = [mob("j", "26.521, Example Campus (2)", "2025-06-01", "2026-11-20")]
    fake.projects = [project("r-1", "26.521", "Example Campus")]
    refresh(client)
    assert fake.windows()[0][0] == "2025-11-18"


def test_every_page_is_read(client, google, fake):
    """Pages of three, with nextOffset a string as in Raken's docs."""
    google.events = [JOB]
    fake.page_size = 3
    fake.projects = [project("r-%d" % i, "26.%03d" % (600 + i), "Example %d" % i)
                     for i in range(7)] + [project("r-1x", "26.501", "Example Clinic")]
    fake.cards = [card("r-1x", day, "w-%d" % i, 1) for day in ("2026-11-16", "2026-11-17")
                  for i in range(5)]
    r = by_key(refresh(client))["job:26.501"]["raken"]
    assert r["state"] == "linked"
    assert r["actual_hours"] == 10 and r["avg_on_site"] == 5
    assert len(fake.card_calls) >= 4


def test_raken_is_called_one_at_a_time(client, google, fake):
    google.events = [mob("j", "26.520, Example Warehouse (2)", "2026-09-01", "2026-11-20")]
    fake.projects = [project("r-1", "26.520", "Example Warehouse")]
    refresh(client)
    assert fake.max_in_flight == 1


# ── Raken-only ────────────────────────────────────────────────────────────────
def test_raken_projects_with_recent_hours_and_no_calendar_job_get_their_own_section(
        client, google, fake):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic"),
                     project("r-2", "26.700", "Example Unscheduled"),
                     project("r-3", "26.701", "Example Quiet"),
                     project("r-4", "", "Example No Number")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8),
                  card("r-2", "2026-11-05", "w-2", 8), card("r-2", "2026-11-10", "w-2", 6),
                  card("r-3", "2026-10-20", "w-3", 8),          # 29 days ago: not recent
                  card("r-4", "2026-11-17", "w-4", 3)]
    body = refresh(client)
    only = {x["uuid"]: x for x in body["raken_only"]}
    assert sorted(only) == ["r-2", "r-4"]
    assert only["r-2"]["name"] == "Example Unscheduled" and only["r-2"]["number"] == "26.700"
    assert only["r-2"]["actual_hours"] == 14
    assert only["r-4"]["number"] is None and only["r-4"]["actual_hours"] == 3
    assert body["raken"]["read_from"] <= "2026-11-04"


def test_a_raken_project_for_a_calendar_job_outside_the_list_is_not_raken_only(
        client, google, fake):
    """Raken-only means no job ON THE CALENDAR has the number, not merely none in the list: a job
    that ended weeks ago with a straggling time card is still a calendar job."""
    google.events = [JOB, mob("o", "26.530, Example Old Job (2)", "2026-09-28", "2026-10-02")]
    fake.projects = [project("r-1", "26.501", "Example Clinic"),
                     project("r-5", "26.530", "Example Old Job"),
                     project("r-6", "26.701", "Example Unscheduled")]
    fake.cards = [card("r-5", "2026-11-16", "w-5", 3), card("r-6", "2026-11-16", "w-6", 2)]
    body = refresh(client)
    assert [p["key"] for p in body["projects"]] == ["job:26.501"]
    assert [x["uuid"] for x in body["raken_only"]] == ["r-6"]


# ── when Raken cannot be read ─────────────────────────────────────────────────
def _calendar_side_still_shows(body):
    assert [p["key"] for p in body["projects"]] == ["job:26.501"]
    assert body["projects"][0]["planned_hours"] == 48


def test_not_connected_says_so_and_never_calls_raken(client, google, fake):
    raken.TOKEN_FILE.unlink()
    google.events = [JOB]
    for body in (refresh(client), get(client)):
        _calendar_side_still_shows(body)
        assert body["raken"]["state"] == "not_connected"
        assert body["raken"]["message"] == "Raken is not connected."
        assert body["projects"][0]["raken"]["state"] == "not_connected"
        assert body["projects"][0]["statuses"] == []
    assert fake.project_calls == 0 and fake.card_calls == []


def test_not_set_up_on_the_server_says_so(client, google, fake, monkeypatch):
    monkeypatch.delenv("RAKEN_TOKEN_KEY")
    google.events = [JOB]
    body = refresh(client)
    assert body["raken"]["state"] == "not_connected"
    assert body["raken"]["message"] == "Raken is not set up on this server yet."
    assert fake.project_calls == 0


def test_an_expired_sign_in_says_an_admin_must_connect_again(client, google, fake):
    fake.valid_refresh.clear()
    google.events = [JOB]
    body = refresh(client)
    _calendar_side_still_shows(body)
    assert body["raken"]["state"] == "expired"
    assert body["raken"]["message"] == raken.EXPIRED_MESSAGE
    assert body["projects"][0]["raken"]["state"] == "expired"


def test_an_account_without_the_public_api_says_raken_has_to_turn_it_on(
        client, google, fake, caplog):
    caplog.set_level("DEBUG")
    fake.refuse = {"message": "made-up refusal text 7731", "code": "API_KEY_NOT_FOUND"}
    google.events = [JOB]
    body = refresh(client)
    _calendar_side_still_shows(body)
    assert body["raken"]["state"] == "not_provisioned"
    assert body["raken"]["message"] == raken.NOT_PROVISIONED_MESSAGE
    assert body["projects"][0]["raken"]["state"] == "not_provisioned"
    assert "made-up refusal text 7731" not in caplog.text
    assert get(client)["raken"]["state"] == "not_provisioned"


def test_raken_unreachable_with_nothing_saved_says_so(client, google, fake):
    fake.down = True
    google.events = [JOB]
    body = refresh(client)
    _calendar_side_still_shows(body)
    assert body["raken"]["state"] == "unreachable"
    assert body["raken"]["message"] == "Raken could not be reached."
    assert body["projects"][0]["raken"]["state"] == "unreachable"


def test_raken_unreachable_after_a_good_refresh_keeps_the_last_numbers_as_stale(
        client, google, fake, monkeypatch):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-17", "w-1", 8)]
    refresh(client)
    fake.down = True
    monkeypatch.setattr(raken_actuals, "now_utc",
                        lambda: dt.datetime(2026, 11, 18, 18, 0, tzinfo=dt.timezone.utc))
    body = refresh(client)
    assert body["raken"]["state"] == "connected" and body["raken"]["stale"] is True
    assert body["raken"]["message"] == "Raken could not be reached."
    assert body["raken"]["as_of"] == "2026-11-18T09:05:00-06:00", "the last good read's time"
    assert by_key(body)["job:26.501"]["raken"]["actual_hours"] == 16


def test_a_good_refresh_clears_the_stale_message(client, google, fake):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.down = True
    refresh(client)
    fake.down = False
    body = refresh(client)
    assert body["raken"]["state"] == "connected" and body["raken"]["stale"] is False
    assert body["raken"]["message"] is None


def test_a_calendar_failure_still_reads_raken_for_the_raken_only_section(client, google, fake):
    google.fail = True
    fake.projects = [project("r-2", "26.700", "Example Unscheduled")]
    fake.cards = [card("r-2", "2026-11-16", "w-2", 8)]
    body = refresh(client)
    assert body["projects"] == [] and body["error"] == "Google Calendar could not be reached."
    assert [x["uuid"] for x in body["raken_only"]] == ["r-2"]


# ── the kept result ───────────────────────────────────────────────────────────
def test_the_last_refresh_survives_a_restart(client, google, fake):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    refresh(client)
    assert raken_actuals.STORE_FILE.exists()
    raken.reset_for_tests()
    raken_actuals.reset_for_tests()              # a restart: nothing in memory, only the file
    calls = (fake.project_calls, len(fake.card_calls))
    body = get(client)
    assert (fake.project_calls, len(fake.card_calls)) == calls
    assert by_key(body)["job:26.501"]["raken"]["actual_hours"] == 8
    assert body["raken"]["as_of"] == "2026-11-18T09:05:00-06:00"


def test_a_result_from_an_earlier_day_never_counts_days_it_did_not_read_as_missed(
        client, google, fake, monkeypatch):
    """Read on Wednesday (through Tuesday), shown on Thursday: Wednesday was booked but not read,
    so it is not a missed day."""
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-17", "w-1", 8)]
    refresh(client)
    monkeypatch.setattr(pc, "today_central", lambda: TODAY + dt.timedelta(days=1))
    pc.cache_clear()
    p = by_key(get(client))["job:26.501"]
    assert p["workdays_so_far"] == 3, "the calendar side counts through Wednesday"
    assert p["raken"]["days_booked"] == 2 and p["raken"]["days_clocked"] == 2
    assert p["statuses"] == ["on_plan"]


def test_a_store_that_cannot_be_written_still_answers_and_never_500s(
        client, google, fake, monkeypatch):
    def full(*_a, **_k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(raken_actuals, "write_json", full)
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    r = client.post(REFRESH)
    assert r.status_code == 200, r.text
    assert by_key(r.json())["job:26.501"]["raken"]["actual_hours"] == 8
    assert "No space left" not in r.text


def later(monkeypatch, minutes):
    """Move the clock `minutes` past the first refresh (Wednesday 09:05 Central)."""
    at = dt.datetime(2026, 11, 18, 15, 5, tzinfo=dt.timezone.utc) + dt.timedelta(minutes=minutes)
    monkeypatch.setattr(raken_actuals, "now_utc", lambda: at)


def test_a_refresh_while_one_is_running_answers_at_once_and_raken_is_read_once(
        client, google, fake):
    """A second press never holds a server thread for the whole Raken read: it answers straight
    away, saying a refresh is running, and the page polls until it is done."""
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    fake.gate = threading.Event()
    out = []
    first = threading.Thread(target=lambda: out.append(client.post(REFRESH)))
    first.start()
    try:
        assert fake.entered.wait(5), "the first refresh never reached Raken"
        started = time.monotonic()
        second = refresh(client)
        during = get(client)
        assert time.monotonic() - started < 5, "the second press waited for the first"
    finally:
        fake.gate.set()
        first.join(15)
    assert second["raken"]["refreshing"] is True and during["raken"]["refreshing"] is True
    assert [r.status_code for r in out] == [200]
    done = out[0].json()
    assert done["raken"]["refreshing"] is False
    assert by_key(done)["job:26.501"]["raken"]["actual_hours"] == 8
    after = get(client)
    assert after["raken"]["refreshing"] is False
    assert by_key(after)["job:26.501"]["raken"]["actual_hours"] == 8
    assert fake.project_calls == 1, "Raken was read once"
    assert fake.max_in_flight == 1


def test_a_second_refresh_soon_after_a_good_one_reads_raken_not_again(
        client, google, fake, monkeypatch):
    """Raken's daily allowance is the whole company's: presses inside the cooldown answer from the
    last read."""
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    refresh(client)
    calls = (fake.project_calls, len(fake.card_calls))
    fake.cards.append(card("r-1", "2026-11-17", "w-1", 8))
    cooldown = raken_actuals.REFRESH_COOLDOWN_S // 60
    later(monkeypatch, cooldown - 1)
    for _ in range(3):
        assert by_key(refresh(client))["job:26.501"]["raken"]["actual_hours"] == 8
    assert (fake.project_calls, len(fake.card_calls)) == calls, "Raken read inside the cooldown"
    later(monkeypatch, cooldown + 1)
    assert by_key(refresh(client))["job:26.501"]["raken"]["actual_hours"] == 16
    assert fake.project_calls == calls[0] + 1


def test_a_refresh_after_a_failed_one_is_never_held_back(client, google, fake, monkeypatch):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    refresh(client)
    later(monkeypatch, 60)
    fake.down = True
    assert refresh(client)["raken"]["stale"] is True
    fake.down = False
    later(monkeypatch, 61)
    body = refresh(client)
    assert body["raken"]["stale"] is False and body["raken"]["message"] is None


def test_a_refresh_while_the_calendar_cannot_be_read_never_shrinks_the_last_read(
        client, google, fake, monkeypatch):
    """With no calendar rows to say how far back to read, the refresh reads at least as far back
    as the last good read did, so no job's Actual hours drop when the calendar comes back."""
    google.events = [mob("j", "26.520, Example Warehouse (2)", "2026-09-01", "2026-11-20")]
    fake.projects = [project("r-1", "26.520", "Example Warehouse")]
    fake.cards = [card("r-1", "2026-09-01", "w-1", 8), card("r-1", "2026-10-01", "w-1", 8),
                  card("r-1", "2026-11-17", "w-1", 8)]
    before = by_key(refresh(client))["job:26.520"]["raken"]
    assert before["actual_hours"] == 24
    pc.cache_clear()
    google.fail = True
    later(monkeypatch, 60)
    failing = refresh(client)
    assert failing["projects"] == [] and failing["error"]
    assert failing["raken"]["read_from"] == "2026-09-01"
    google.fail = False
    pc.cache_clear()
    after = by_key(get(client))["job:26.520"]["raken"]
    assert after["actual_hours"] == 24 and after["days_booked"] == before["days_booked"]


def test_a_fault_before_the_raken_read_still_answers_and_frees_the_next_refresh(
        client, google, fake, monkeypatch):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    real = raken_actuals.span

    def broken(*_a, **_k):
        raise RuntimeError("made-up fault")
    monkeypatch.setattr(raken_actuals, "span", broken)
    r = client.post(REFRESH)
    assert r.status_code == 200, r.text
    _calendar_side_still_shows(r.json())
    assert r.json()["raken"]["state"] == "not_refreshed"
    monkeypatch.setattr(raken_actuals, "span", real)
    assert by_key(refresh(client))["job:26.501"]["raken"]["actual_hours"] == 8


def test_when_the_raken_side_cannot_be_set_the_block_keeps_its_shape_and_says_so(
        client, google, fake, monkeypatch):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    good = refresh(client)

    def broken(*_a, **_k):
        raise RuntimeError("made-up fault")
    monkeypatch.setattr(raken_actuals, "_row", broken)
    body = get(client)
    _calendar_side_still_shows(body)
    assert set(body["raken"]) == set(good["raken"]), "the same block, whatever went wrong"
    assert body["raken"]["state"] == "unreachable"
    assert body["raken"]["message"] == raken_actuals.NOT_SHOWN_MESSAGE
    assert body["raken"]["message"] != plan_vs_actual.ERR_BUILD, "not a calendar error"
    assert body["projects"][0]["raken"] == {"state": "unreachable"}
    assert body["projects"][0]["statuses"] == [] and body["raken_only"] == []


def test_a_load_that_races_a_save_never_puts_the_older_copy_back(fake, monkeypatch):
    raken_actuals._save({"result": {"as_of": "older"}, "failure": None})
    raken_actuals.reset_for_tests()
    real = raken_actuals.STORE_FILE
    monkeypatch.setattr(raken_actuals, "write_json", lambda *_a, **_k: None)

    class Racing:
        def read_text(self, encoding=None):
            text = real.read_text(encoding=encoding)
            raken_actuals._save({"result": {"as_of": "newer"}, "failure": None})
            return text
    monkeypatch.setattr(raken_actuals, "STORE_FILE", Racing())
    raken_actuals.load()
    assert raken_actuals.load()["result"]["as_of"] == "newer"


# ── access and secrecy ────────────────────────────────────────────────────────
def test_every_signed_in_role_sees_the_numbers_and_can_refresh(client, google, fake, monkeypatch):
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    for role in ("user", "estimator", "admin"):
        monkeypatch.setattr(main.profiles, "get_by_email",
                            lambda e, role=role: {"id": "u", "email": e, "role": role,
                                                  "status": "active"})
        main._profile_cache_clear()
        assert by_key(refresh(client))["job:26.501"]["raken"]["actual_hours"] == 8
        assert by_key(get(client))["job:26.501"]["raken"]["actual_hours"] == 8


def test_signed_out_the_refresh_is_refused(client, google, fake, monkeypatch, real_verify_token):
    monkeypatch.setattr(supabase_client, "verify_token", real_verify_token)
    r = client.post(REFRESH, headers={"authorization": ""})
    assert r.status_code == 401
    assert fake.project_calls == 0


def test_nothing_read_from_raken_reaches_the_log(client, google, fake, caplog):
    caplog.set_level("DEBUG")
    google.events = [JOB]
    fake.projects = [project("r-made-up-uuid-1", "26.501", "Example Clinic Secretname"),
                     project("r-made-up-uuid-2", "26.501", "Example Clinic Othername"),
                     project("r-made-up-uuid-3", "26.777", "Example Hidden Name")]
    fake.cards = [card("r-made-up-uuid-3", "2026-11-16", "w-made-up-worker", 8)]
    refresh(client)
    for leak in ("Secretname", "Othername", "Hidden Name", "26.777", "r-made-up-uuid",
                 "w-made-up-worker", "made-up-access", "made-up-refresh"):
        assert leak not in caplog.text, leak


def test_a_refresh_that_would_need_too_many_calls_stops_plainly(client, google, fake, monkeypatch):
    monkeypatch.setattr(raken_actuals, "CALL_CAP", 2)
    google.events = [mob("j", "26.520, Example Warehouse (2)", "2026-09-01", "2026-11-20")]
    fake.projects = [project("r-1", "26.520", "Example Warehouse")]
    body = refresh(client)
    assert body["raken"]["state"] == "unreachable"
    assert body["raken"]["message"] == raken_actuals.TOO_MANY_MESSAGE
    assert fake.project_calls + len(fake.card_calls) <= 2


def test_the_call_cap_counts_the_project_calls_and_is_never_passed(
        client, google, fake, monkeypatch):
    monkeypatch.setattr(raken_actuals, "CALL_CAP", 3)
    google.events = [JOB]
    fake.page_size = 1
    fake.projects = [project("r-%d" % i, "26.%03d" % (600 + i), "Example %d" % i) for i in range(6)]
    body = refresh(client)
    assert body["raken"]["state"] == "unreachable"
    assert body["raken"]["message"] == raken_actuals.TOO_MANY_MESSAGE
    assert fake.project_calls + len(fake.card_calls) == 3


def test_a_listing_longer_than_the_page_cap_fails_instead_of_keeping_part_of_it(
        client, google, fake, monkeypatch):
    """A time-card read cut short would undercount Actual hours and show jobs Behind that are not."""
    monkeypatch.setattr(raken, "_PAGE_CAP", 2)
    google.events = [JOB]
    fake.page_size = 1
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8), card("r-1", "2026-11-16", "w-2", 8),
                  card("r-1", "2026-11-17", "w-1", 8)]
    body = refresh(client)
    assert body["raken"]["state"] == "unreachable"
    assert body["raken"]["message"] == raken_actuals.TOO_MANY_MESSAGE
    assert "actual_hours" not in by_key(body)["job:26.501"]["raken"]


def test_a_next_offset_raken_could_not_mean_ends_the_paging(client, google, fake):
    """A non-ASCII digit passes str.isdigit() but not int(): it ends the paging, as any other
    unreadable nextOffset does, and never fails the read."""
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    fake.cards = [card("r-1", "2026-11-16", "w-1", 8)]
    fake.projects_next = "\u00b2"
    r = by_key(refresh(client))["job:26.501"]["raken"]
    assert r["state"] == "linked" and r["actual_hours"] == 8
    assert fake.project_calls == 1


def test_inactive_raken_projects_are_asked_for_too(client, google, fake):
    """A job finished last week may have its Raken project set Inactive already; it must still
    link."""
    google.events = [JOB]
    fake.projects = [project("r-1", "26.501", "Example Clinic")]
    refresh(client)
    assert fake.project_params
    assert all(sorted(s) == ["ACTIVE", "INACTIVE"] for s in fake.project_params)
