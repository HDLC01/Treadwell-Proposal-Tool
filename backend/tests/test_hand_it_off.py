"""Handing a won project to operations — the press that takes a card off the board.

Hanz, 2026-08-28: "Once we receive the Contact Info, we indicate it as handed off... We need to add
a button on the Project container in the Active project named as 'Hand it off'."

WHY THIS FIELD EXISTS AT ALL, since the obvious question is why a fourth outcome earns storage when
"won" is derived. Between 2026-08-20 and 2026-08-28 winning a job took its card off the Active
board by itself — `isWon` was the routing question — so one press said both "we got it" and "we are
done looking at it". The second half was wrong: a won job still owes a deposit and a set of
contacts, and the sales meeting is run off that board. Handing off is a HUMAN ACT with no timestamp
anywhere in either database to derive it from, which is exactly what earns it a stored field where
"won" could be computed.

`test_handed_off_tab.py` covers the front half — the tab, the routing, the buttons. This file covers
the write, and the four places the stamp has to survive on its way back to a card:

  * BOTH summary paths. The fast one selects NAMED json paths rather than the blob, so a key nobody
    names reaches no card. Worse here than for the won mark: `won_at` decides a COLUMN, this decides
    a TAB, so an unnamed key does not degrade the board, it empties a tab. The projection is
    EXECUTED below against a fake that honours the select, not grepped.
  * a SENT project needs it, and needs it most — nearly every job that reaches operations was sent.
    The portal has no column for it, so the pipeline merge stamps it onto the portal's own rows.
  * an UNSENT project needs it too. Rare but real: a job won on the phone, priced, and passed
    straight to operations without the customer ever being sent the paperwork.
  * bring-back has to clear it, or the card the estimator just reopened goes straight back to the
    Handed Off tab, where they would not look for it.
"""
import importlib
import re

import drafts
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)
drafts = importlib.import_module("drafts")


def _seed(fake_supabase, data=None):
    store = {"drafts": [{"id": "a", "data": data if data is not None else {"project_name": "Live"},
                         "owner_email": "u@x.com", "created_at": "2026-01-01",
                         "updated_at": "2026-01-02", "deleted_at": None}],
             "events": []}
    return fake_supabase(store), store


# ── A. the store ─────────────────────────────────────────────────────────────
def test_the_button_records_who_and_when(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_handed_off("a", True, "hanz@wetreadwell.com") is True
    mark = store["drafts"][0]["data"]["handed_off"]
    assert mark["by"] == "hanz@wetreadwell.com"
    assert mark["at"], "no timestamp, so the Handed Off tab has nothing to sort or show"


def test_clearing_it_removes_the_key_rather_than_blanking_it(fake_supabase, monkeypatch):
    """An empty object is truthy in JS. isHandedOff reads the stamp's presence, so a `{"at": null}`
    left behind would keep the card on the Handed Off tab forever — an undo that undoes nothing."""
    fake, store = _seed(fake_supabase, {"project_name": "Live",
                                        "handed_off": {"at": "2026-08-28", "by": "h@x"}})
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_handed_off("a", False, "h@x") is True
    assert "handed_off" not in store["drafts"][0]["data"]


def test_both_writes_leave_an_event_naming_what_happened(fake_supabase, monkeypatch):
    """Two words, not one with a flag, because history.js renders the action verbatim and "handed
    off to operations" and "brought back onto the board" are different things that happened."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_handed_off("a", True, "h@x")
    drafts.set_handed_off("a", False, "h@x")
    assert [e["action"] for e in store["events"]] == ["handed_off", "not_handed_off"]


def test_handing_a_job_off_does_not_bump_updated_at(fake_supabase, monkeypatch):
    """Recording an outcome is not work on the estimate. Shuffling a project to the top of a list
    sorted by date-updated on its way OFF the board would be backwards."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_handed_off("a", True, "h@x")
    assert store["drafts"][0]["updated_at"] == "2026-01-02"


def test_the_rest_of_the_blob_survives(fake_supabase, monkeypatch):
    """The whole `data` blob is rewritten on every one of these writes, so a copy that dropped a key
    would lose an estimate rather than a flag."""
    fake, store = _seed(fake_supabase, {"project_name": "Nearman Creek", "sqft": 12000,
                                        "generate_result": {"work_type": "epoxy"}})
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_handed_off("a", True, "h@x")
    data = store["drafts"][0]["data"]
    assert data["project_name"] == "Nearman Creek" and data["sqft"] == 12000
    assert data["generate_result"] == {"work_type": "epoxy"}


def test_handing_off_and_winning_are_two_independent_marks(fake_supabase, monkeypatch):
    """The whole 2026-08-28 change in one assertion. If either writer touched the other's key,
    winning would still take the card off the board and nothing would have been fixed."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_won("a", True, "h@x")
    drafts.set_handed_off("a", True, "h@x")
    data = store["drafts"][0]["data"]
    assert data["won"] and data["handed_off"], "one writer clobbered the other"
    drafts.set_handed_off("a", False, "h@x")
    assert store["drafts"][0]["data"]["won"], "bringing a card back also erased the win"


def test_the_store_does_not_second_guess_whether_the_job_was_won(fake_supabase, monkeypatch):
    """DELIBERATE, and the argument is in set_handed_off's docstring. Hand it off only renders on a
    card isWon already accepts, so the gate is real and lives in one place. A second copy of it here
    would give the two a way to disagree, and it would refuse a legitimate correction — a job handed
    off, un-marked won by mistake, and re-marked — for nothing."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_handed_off("a", True, "h@x") is True
    assert store["drafts"][0]["data"]["handed_off"]


def test_an_unknown_project_says_so(fake_supabase, monkeypatch):
    fake, _ = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_handed_off("nope", True) is False
    assert drafts.set_handed_off("nope", False) is False


def test_bring_it_back_clears_the_hand_off_with_everything_else(fake_supabase, monkeypatch):
    """One press, one write, the card back on the live board. Leaving the hand-off behind would put
    it straight onto the Handed Off tab, which is not where the estimator who just pressed Bring it
    back is looking."""
    fake, store = _seed(fake_supabase, {"project_name": "Live",
                                        "won": {"at": "2026-08-20"},
                                        "handed_off": {"at": "2026-08-28"},
                                        "closed_lost": {"at": "2026-08-27"},
                                        "on_hold": {"at": "2026-08-26"}})
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.clear_outcome("a", "h@x") is True
    data = store["drafts"][0]["data"]
    assert not any(k in data for k in ("won", "handed_off", "closed_lost", "on_hold"))
    assert data["project_name"] == "Live"


# ── B. both summary paths carry it out ───────────────────────────────────────
def test_the_full_blob_summary_exposes_the_stamp():
    s = drafts._summary({"id": "a", "data": {
        "project_name": "Nearman Creek",
        "handed_off": {"at": "2026-08-28T15:00:00+00:00", "by": "h@x"}}})
    assert s["handed_off_at"] == "2026-08-28T15:00:00+00:00"


def test_a_project_nobody_handed_off_reports_none_not_a_blank():
    """`or None` is what stops an empty object from producing a truthy value: isHandedOff reads this
    field's truthiness, so `{}` arriving as `{}` would move the ENTIRE Active board onto the Handed
    Off tab in one deploy."""
    assert drafts._summary({"id": "a", "data": {"project_name": "Live"}})["handed_off_at"] is None
    assert drafts._summary({"id": "a", "data": {"handed_off": {}}})["handed_off_at"] is None


# The fast path's projection, EXECUTED. `_build_summaries` selects named json paths rather than the
# blob, so the only way a field reaches a card is by being named in that string — and asserting the
# string contains it proves the string, not the summary. This fake honours the select the way
# PostgREST does, so a field dropped from `cols` comes back absent here too.
#
# A near-twin of this fake lives in test_mark_won.py, which is the file that first needed it. It is
# copied rather than shared because the two are proving different fields and sharing it means
# editing that file; if a third file needs it, that is the moment it belongs in conftest.
class _ProjectingTable:
    def __init__(self, store, name):
        self.store, self.name, self.cols = store, name, ""

    def select(self, cols="*", *a, **k):
        self.cols = cols
        return self

    def order(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def in_(self, *a, **k):
        return self

    def is_(self, *a, **k):
        return self

    @property
    def not_(self):
        return self

    def execute(self):
        rows = self.store.get(self.name) or []
        if self.name != "drafts":
            return type("R", (), {"data": []})()
        out = [{spec.split(":", 1)[0] if ":" in spec else spec:
                _jsonpath(r, spec.split(":", 1)[1] if ":" in spec else spec)
                for spec in self.cols.split(",")} for r in rows]
        return type("R", (), {"data": out})()


def _jsonpath(row, path):
    """`data->handed_off->>at` against a Python row, keeping PostgREST's text/object distinction:
    the LAST operator decides, `->>` yielding text and `->` yielding the object itself."""
    ops = re.findall(r"->>|->", path)
    parts = re.split(r"->>|->", path)
    cur = row.get(parts[0])
    for key in parts[1:]:
        cur = cur.get(key) if isinstance(cur, dict) else None
    if cur is None:
        return None
    if not ops or ops[-1] == "->>":
        if isinstance(cur, bool):
            return "true" if cur else "false"
        return cur if isinstance(cur, str) else str(cur)
    return cur


class _ProjectingClient:
    def __init__(self, store):
        self.store = store

    def table(self, name):
        return _ProjectingTable(self.store, name)


def _projected(monkeypatch, data):
    store = {"drafts": [{"id": "d1", "owner_email": "k@x.com", "deleted_at": None,
                         "created_at": "2026-08-01", "updated_at": "2026-08-02", "data": data}]}
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    got = drafts._build_summaries(trashed=False, limit=10)
    assert len(got) == 1, "the fake projection broke the read; fix the fake, not the assertion"
    return got[0]


def test_the_fast_projection_carries_the_stamp_to_the_card(monkeypatch):
    """The one that matters. Executed through the projection, so dropping `handed_off_at` from
    `cols` fails here rather than only on somebody's screen — and what it costs there is the whole
    Handed Off tab, which reads empty while every handed-off card sits back on Active."""
    got = _projected(monkeypatch, {"project_name": "Nearman Creek",
                                   "generate_result": {"work_type": "epoxy"},
                                   "handed_off": {"at": "2026-08-28T15:00:00+00:00", "by": "h@x"}})
    assert got["handed_off_at"] == "2026-08-28T15:00:00+00:00"


def test_the_fast_projection_still_answers_none_for_a_project_on_the_board(monkeypatch):
    assert _projected(monkeypatch, {"project_name": "Live"})["handed_off_at"] is None


def test_the_stamp_does_not_ride_in_on_the_won_mark(monkeypatch):
    """The two json paths differ by one word. A copy-paste that left `data->won->>at` under the new
    name would pass every test above and hand off every won job the moment it was won — which is
    precisely the behaviour this change exists to end."""
    got = _projected(monkeypatch, {"project_name": "Won not handed off",
                                   "won": {"at": "2026-08-20T15:00:00+00:00", "by": "h@x"}})
    assert got["won_at"] == "2026-08-20T15:00:00+00:00"
    assert got["handed_off_at"] is None


# ── C. the board rows ────────────────────────────────────────────────────────
def _summary_row(**kw):
    s = {"id": "d1", "project_name": "Nearman Creek", "has_files": True,
         "updated_at": "2026-08-10", "total": 41250}
    s.update(kw)
    return s


def test_a_synthesised_not_sent_row_carries_the_stamp():
    """Unsent AND handed off is rare but real — a job won on the phone, priced, and passed to
    operations without the customer ever being sent the paperwork."""
    r = main._not_sent_rows([_summary_row(handed_off_at="2026-08-28T15:00:00+00:00")], [])[0]
    assert r["handed_off_at"] == "2026-08-28T15:00:00+00:00"


def test_an_unhanded_not_sent_row_says_none():
    """Unconditional, unlike the portal rows below, because this row is ours from nothing — None
    here is the whole truth rather than a key invented over a portal field."""
    assert main._not_sent_rows([_summary_row()], [])[0]["handed_off_at"] is None


def _portal_row(pid="d1", **kw):
    r = {"proposal_id": pid, "project_name": "Oak Grove", "proposal_status": "sent",
         "sent_at": "2026-08-01T10:00:00+00:00"}
    r.update(kw)
    return r


def _wire(monkeypatch, rows, summaries):
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": rows})
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: summaries)


def _pipeline():
    r = client.get("/api/portal/pipeline")
    assert r.status_code == 200, r.text
    return {p["proposal_id"]: p for p in r.json()["proposals"]}


def test_a_sent_project_gets_the_stamp_too(monkeypatch):
    """The half that carries almost all the traffic: nearly every job that reaches operations was
    sent. The portal row has no such column, so without this merge the tab would only work for the
    unsent handful."""
    _wire(monkeypatch, [_portal_row("d1")],
          [_summary_row(id="d1", handed_off_at="2026-08-28T15:00:00+00:00")])
    out = _pipeline()
    assert len(out) == 1, "the sent row was duplicated as a not-sent card"
    assert out["d1"]["handed_off_at"] == "2026-08-28T15:00:00+00:00"


def test_a_sent_project_nobody_handed_off_gets_no_such_field(monkeypatch):
    """Not `handed_off_at: null` on every row on the board. The portal has no such column, and
    inventing an empty one would claim we had looked."""
    _wire(monkeypatch, [_portal_row("d1")], [_summary_row(id="d1")])
    assert "handed_off_at" not in _pipeline()["d1"]


def test_the_stamp_survives_a_project_the_drafts_list_has_never_heard_of(monkeypatch):
    """An unmatched portal row is left ALONE rather than stamped with a null, and one unreadable
    draft must not cost the board."""
    _wire(monkeypatch, [_portal_row("d1"), _portal_row("d2")],
          [_summary_row(id="d1", handed_off_at="2026-08-28T15:00:00+00:00")])
    out = _pipeline()
    assert out["d1"]["handed_off_at"] == "2026-08-28T15:00:00+00:00"
    assert "handed_off_at" not in out["d2"]


# ── D. the endpoint ──────────────────────────────────────────────────────────
def _api(monkeypatch, seen):
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.drafts, "set_handed_off",
                        lambda pid, on, actor: (seen.append(("hand", pid, on, actor)), True)[1])
    monkeypatch.setattr(main.drafts, "set_won",
                        lambda pid, won, actor: (seen.append(("won", pid, won, actor)), True)[1])
    monkeypatch.setattr(main.drafts, "clear_outcome",
                        lambda pid, actor: (seen.append(("clear", pid, None, actor)), True)[1])
    monkeypatch.setattr(main.drafts, "latest_revision_no", lambda pid: None)


def test_the_route_hands_it_off(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status", json={"status": "handed_off"})
    assert r.status_code == 200, r.text
    assert seen == [("hand", "d1", True, "hanz@wetreadwell.com")]
    assert r.json()["status"] == "handed_off"


def test_the_route_brings_it_back_onto_the_board(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status", json={"status": "not_handed_off"})
    assert r.status_code == 200, r.text
    assert seen == [("hand", "d1", False, "hanz@wetreadwell.com")]
    assert r.json()["status"] == "not_handed_off"


def test_handing_off_is_not_the_same_call_as_winning(monkeypatch):
    """Two narrow statuses that each say what they did, matching `won`/`not_won` exactly. If either
    routed through the other's writer, the undo would clear the wrong mark."""
    seen = []
    _api(monkeypatch, seen)
    client.post("/api/draft/d1/status", json={"status": "handed_off"})
    assert [s[0] for s in seen] == ["hand"], "handing off went through the won writer"
    seen.clear()
    client.post("/api/draft/d1/status", json={"status": "won"})
    assert [s[0] for s in seen] == ["won"], "winning also handed the job off"


def test_a_project_that_is_not_there_is_a_404(monkeypatch):
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.drafts, "set_handed_off", lambda pid, on, actor: False)
    for status in ("handed_off", "not_handed_off"):
        r = client.post("/api/draft/gone/status", json={"status": status})
        assert r.status_code == 404, (status, r.text)


def test_a_write_that_blew_up_is_reported_not_swallowed(monkeypatch):
    """502, not a cheerful 200. The drawer repaints itself on ok, so a swallowed failure paints the
    card as handed off and it reappears on Active at the next load with nobody told why."""
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")

    def _boom(pid, on, actor):
        raise RuntimeError("postgrest said no")

    monkeypatch.setattr(main.drafts, "set_handed_off", _boom)
    assert client.post("/api/draft/d1/status",
                       json={"status": "handed_off"}).status_code == 502


def test_handing_off_needs_no_reason_and_no_note(monkeypatch):
    """There is no vocabulary of ways to hand a job off, and the required-comment rule belongs to
    the two CLOSING paths only. A stray reason riding along must not turn this into a 422."""
    seen = []
    _api(monkeypatch, seen)
    assert client.post("/api/draft/d1/status",
                       json={"status": "handed_off", "reason": "vibes"}).status_code == 200
    assert seen == [("hand", "d1", True, "hanz@wetreadwell.com")]


def test_a_near_miss_status_is_still_refused(monkeypatch):
    """The branch matches two exact strings. Anything close to them must fall through to the 422
    rather than being read charitably."""
    seen = []
    _api(monkeypatch, seen)
    for junk in ("handoff", "hand_off", "handed", "un_handed_off", "not_handed"):
        assert client.post("/api/draft/d1/status",
                           json={"status": junk}).status_code == 422, junk
    assert seen == []
