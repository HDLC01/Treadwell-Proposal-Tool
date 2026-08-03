"""Treadwell's own calendar entries — the writable half of the Bid Calendar.

The boundary these tests defend: **Basisboard bids are a read-only mirror.** Our
integration never writes upstream, so an edit to a mirrored bid could not be saved there
and would silently revert on the next sync. A staff member who edits a bid, watches it
change, and finds the old value back five minutes later would rightly conclude the tool
loses data. So there is no route that edits one, and the UI gives their cards no edit
affordance at all.

Everything here is about the other half: entries created in the tool, which we own
outright and which are the only ones left once Treadwell is off Basisboard.

The rest is the quiet stuff that costs a job when it's wrong — a deadline stored an hour
off, a "$1,200" paste becoming 1200.00 or an error, a delete that actually destroys a bid
date, and a save that reports success to a row somebody else already removed.
"""
import re
from datetime import datetime, timezone

import pytest

import calendar_events as ce


# ── validation ────────────────────────────────────────────────────────
def test_a_nameless_entry_is_refused_with_a_usable_message():
    """The name is how it's found again — a blank one is a row nobody can act on."""
    with pytest.raises(ce.ValidationError) as e:
        ce.validate({"title": "   "})
    assert "name" in str(e.value).lower()


def test_titles_are_squashed_and_capped():
    out = ce.validate({"title": "  Monticello   Trails\n\tMiddle School  "})
    assert out["title"] == "Monticello Trails Middle School"
    assert len(ce.validate({"title": "x" * 900})["title"]) == 500


@pytest.mark.parametrize("raw,expect", [
    (1200, 1200.0),
    ("1200", 1200.0),
    ("$1,200", 1200.0),          # pasted from a spreadsheet
    ("  $1,200.50 ", 1200.50),
    ("", None),
    (None, None),
])
def test_money_accepts_what_people_actually_type(raw, expect):
    assert ce.validate({"title": "x", "value": raw})["value"] == expect


@pytest.mark.parametrize("bad", ["abc", "1,2,3.4.5", "$-"])
def test_an_unreadable_value_is_refused_rather_than_stored_as_zero(bad):
    """Silently storing 0 would make a real bid look worthless on the day header total."""
    with pytest.raises(ce.ValidationError):
        ce.validate({"title": "x", "value": bad})


def test_a_negative_or_absurd_value_is_refused():
    with pytest.raises(ce.ValidationError):
        ce.validate({"title": "x", "value": -5})
    with pytest.raises(ce.ValidationError):
        ce.validate({"title": "x", "value": 1e12})


def test_an_unknown_kind_is_refused():
    with pytest.raises(ce.ValidationError):
        ce.validate({"title": "x", "kind": "wedding"})


def test_kind_defaults_to_bid_and_is_case_insensitive():
    assert ce.validate({"title": "x"})["kind"] == "bid"
    assert ce.validate({"title": "x", "kind": "Site_Visit"})["kind"] == "site_visit"


def test_an_unknown_key_is_dropped_rather_than_persisted():
    """An unexpected key is a client bug. Storing it makes the row shape unpredictable for
    every later reader, and the insert would fail on a column that doesn't exist."""
    out = ce.validate({"title": "x", "is_admin": True, "deleted_at": "now"})
    assert set(out) <= set(ce.WRITABLE)
    assert "is_admin" not in out and "deleted_at" not in out


def test_a_partial_update_only_touches_what_was_sent():
    """A PATCH that also wrote the untouched columns would blank a deadline every time
    somebody renamed an entry."""
    out = ce.validate({"title": "New name"}, partial=True)
    assert out == {"title": "New name"}


def test_a_full_create_fills_every_writable_column():
    """The opposite guarantee: a create must not leave a column absent, or the row's shape
    depends on which fields the form happened to send."""
    out = ce.validate({"title": "x"}, partial=False)
    assert set(out) == set(ce.WRITABLE)


def test_an_obviously_broken_estimator_address_is_refused_but_odd_ones_are_not():
    """The roster is the authority on who exists. Rejecting anything merely unusual would
    block a legitimate address, so only obvious nonsense is refused."""
    assert ce.validate({"title": "x", "estimator_email": "Kyle.Loseke@WeTreadwell.com"}
                       )["estimator_email"] == "kyle.loseke@wetreadwell.com"
    for bad in ("kyle", "@wetreadwell.com", "kyle@"):
        with pytest.raises(ce.ValidationError):
            ce.validate({"title": "x", "estimator_email": bad})


# ── deadlines: the part that costs a job when it's wrong ──────────────
def test_a_deadline_keeps_its_time_of_day():
    """Storing a bare date would throw away the cut-off time, which is most of what a bid
    deadline IS — 2pm and 5pm on the same day are different jobs."""
    got = ce.parse_deadline("2026-08-14T19:00:00+00:00")
    assert "19:00" in got


def test_a_naive_deadline_is_read_as_utc_not_as_the_servers_zone():
    """The frontend converts Central to UTC before sending. If the server guessed its own
    local zone here, a 2pm Central deadline would land at 9am on the calendar — and it
    would only be wrong on machines whose clock differs from the container's."""
    got = ce.parse_deadline("2026-08-14T19:00:00")
    assert datetime.fromisoformat(got).utcoffset() == timezone.utc.utcoffset(None)
    assert "19:00" in got


def test_an_offset_deadline_is_normalised_to_utc():
    got = ce.parse_deadline("2026-08-14T14:00:00-05:00")
    assert datetime.fromisoformat(got) == datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc)


def test_a_z_suffixed_deadline_is_accepted():
    """What JSON.stringify(new Date()) produces, so the common case must work."""
    assert ce.parse_deadline("2026-08-14T19:00:00Z") is not None


def test_no_deadline_is_allowed_and_stays_empty():
    """A bid can be on the calendar before its date is known — those are the ones that go
    quiet, and the page has a tray for them."""
    assert ce.parse_deadline("") is None
    assert ce.parse_deadline(None) is None
    assert ce.validate({"title": "x", "deadline_at": ""})["deadline_at"] is None


def test_an_unreadable_deadline_is_refused_rather_than_dropped():
    """Dropping it would put the entry in the undated tray while the person believed they
    had set a date — the failure would be invisible until the bid was missed."""
    with pytest.raises(ce.ValidationError):
        ce.parse_deadline("next tuesday")


# ── the row the calendar sees ─────────────────────────────────────────
def test_our_rows_speak_the_same_vocabulary_as_the_basisboard_ones():
    """The grid renders both from one code path. If ours used different key names the page
    would need a branch per source, and every later feature would need two."""
    row = ce._shape({"id": "1", "title": "Alpha", "deadline_at": "2026-08-14T19:00:00+00:00",
                     "value": 1200, "estimator_email": "kyle@x.com", "stage": "bidding"})
    for key in ("id", "name", "bid_deadline_at", "quote", "estimator_ids", "stage_id",
                "archived"):
        assert key in row, key
    assert row["name"] == "Alpha"
    assert row["quote"] == 1200
    assert row["estimator_ids"] == ["kyle@x.com"]


def test_our_rows_are_marked_editable_and_basisboards_are_not():
    """The UI decides whether to offer an edit button from THIS flag, so it is computed in
    one place rather than inferred from the absence of a field."""
    row = ce._shape({"id": "1", "title": "Alpha"})
    assert row["source"] == "treadwell"
    assert row["editable"] is True


def test_an_unassigned_row_has_an_empty_estimator_list_not_a_list_with_nothing_in_it():
    """`[""]` would count as assigned everywhere the calendar checks `.length`, so the
    "No estimator" total would silently read zero."""
    row = ce._shape({"id": "1", "title": "Alpha", "estimator_email": None})
    assert row["estimator_ids"] == []


def test_a_row_never_reports_itself_archived():
    """`archived` filters the calendar. Ours have no archive concept, and a missing key
    would read as undefined rather than false in the browser."""
    assert ce._shape({"id": "1", "title": "x"})["archived"] is False


def test_a_nameless_stored_row_still_renders_something():
    """Defence for a row written before validation existed, or by hand in SQL."""
    assert ce._shape({"id": "1", "title": ""})["name"] == "Untitled"


# ── the read/write surface ────────────────────────────────────────────
class _FakeTable:
    """Minimal stand-in for the supabase query builder — enough to record what was sent."""

    def __init__(self, store):
        self.store = store
        self._filters = {}
        self._payload = None
        self._op = None

    def select(self, *_a, **_k):
        self._op = "select"; return self

    def insert(self, row):
        self._op = "insert"; self._payload = row; return self

    def update(self, row):
        self._op = "update"; self._payload = row; return self

    def eq(self, col, val):
        self._filters[col] = val; return self

    def is_(self, col, val):
        self._filters[col] = ("is", val); return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        self.store.setdefault("calls", []).append(
            {"op": self._op, "payload": self._payload, "filters": dict(self._filters)})
        if self._op == "insert":
            self.store["rows"].append(self._payload)
            return type("R", (), {"data": [self._payload]})()
        if self._op == "update":
            for r in self.store["rows"]:
                if r.get("id") == self._filters.get("id"):
                    r.update(self._payload)
            return type("R", (), {"data": []})()
        rows = self.store["rows"]
        if "id" in self._filters:
            rows = [r for r in rows if r.get("id") == self._filters["id"]]
        if self._filters.get("deleted_at") == ("is", "null"):
            rows = [r for r in rows if not r.get("deleted_at")]
        return type("R", (), {"data": list(rows)})()


@pytest.fixture
def store(monkeypatch):
    st = {"rows": [], "calls": []}
    monkeypatch.setattr(ce, "get_client",
                        lambda: type("C", (), {"table": lambda _s, _n: _FakeTable(st)})())
    return st


def test_creating_an_entry_stamps_an_id_an_owner_and_both_timestamps(store):
    row = ce.create_event({"title": "Alpha", "deadline_at": "2026-08-14T19:00:00Z"},
                          "hanz@wetreadwell.com")
    written = store["rows"][0]
    assert re.fullmatch(r"[0-9a-f-]{36}", written["id"])
    assert written["owner_email"] == "hanz@wetreadwell.com"
    assert written["created_at"] and written["updated_at"]
    assert row["name"] == "Alpha" and row["editable"] is True


def test_creating_an_invalid_entry_writes_nothing(store):
    with pytest.raises(ce.ValidationError):
        ce.create_event({"title": ""}, "hanz@wetreadwell.com")
    assert not store["rows"], "a rejected entry still reached the database"


def test_updating_a_missing_entry_returns_none_so_the_caller_can_404(store):
    """Reporting a cheerful success for a row that no longer exists is how two people
    overwrite each other silently — the entry may have been deleted in another tab."""
    assert ce.update_event("nope", {"title": "New"}) is None


def test_updating_only_writes_the_sent_fields_plus_a_timestamp(store):
    ce.create_event({"title": "Alpha", "deadline_at": "2026-08-14T19:00:00Z"}, "a@b.c")
    eid = store["rows"][0]["id"]
    store["calls"].clear()
    ce.update_event(eid, {"title": "Beta"})
    upd = next(c for c in store["calls"] if c["op"] == "update")
    assert set(upd["payload"]) == {"title", "updated_at"}
    assert store["rows"][0]["deadline_at"] is not None, "the deadline was collateral damage"


def test_an_empty_update_is_refused(store):
    ce.create_event({"title": "Alpha"}, "a@b.c")
    with pytest.raises(ce.ValidationError):
        ce.update_event(store["rows"][0]["id"], {})


def test_deleting_is_soft(store):
    """A calendar is a work queue. A delete that truly destroyed a bid deadline could cost
    a job, and every other destructive action in this app is recoverable."""
    ce.create_event({"title": "Alpha"}, "a@b.c")
    eid = store["rows"][0]["id"]
    assert ce.delete_event(eid) is True
    assert store["rows"][0]["deleted_at"], "the row was not tombstoned"
    assert store["rows"], "the row was actually removed"


def test_deleting_twice_reports_the_second_as_gone(store):
    ce.create_event({"title": "Alpha"}, "a@b.c")
    eid = store["rows"][0]["id"]
    assert ce.delete_event(eid) is True
    assert ce.delete_event(eid) is False


def test_a_deleted_entry_disappears_from_the_list_and_from_get(store):
    ce.create_event({"title": "Alpha"}, "a@b.c")
    eid = store["rows"][0]["id"]
    ce.delete_event(eid)
    assert ce.list_events() == []
    assert ce.get_event(eid) is None


def test_the_list_query_asks_only_for_live_rows(store):
    """Belt and braces on the filter itself: if the query stopped excluding tombstones,
    deleted entries would quietly reappear on the calendar."""
    ce.list_events()
    sel = next(c for c in store["calls"] if c["op"] == "select")
    assert sel["filters"].get("deleted_at") == ("is", "null")


def test_a_broken_table_degrades_to_an_empty_list_rather_than_an_error(monkeypatch):
    """The calendar's Basisboard half must still render. A raise here would take down a
    page that mostly shows something else — and the table may genuinely not exist yet on a
    box where the DDL hasn't been run."""
    def _boom():
        raise RuntimeError("relation \"calendar_events\" does not exist")
    monkeypatch.setattr(ce, "get_client", _boom)
    assert ce.list_events() == []
