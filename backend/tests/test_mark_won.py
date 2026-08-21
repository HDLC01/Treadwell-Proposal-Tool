"""Marking a project won by hand.

Hanz, 2026-08-19: "Is there any way to also mark as won for now other than after the deposit has
been received".

Won was DERIVED ONLY — approved AND the money question settled (`isWon` in crm-core.js). That is the
honest definition of a finished job, and useless for the commonest way we learn we won one: a verbal
yes on the phone, days before the customer clicks Approve and weeks before the deposit lands. Until
then the board called a won job Active. Lost became markable by hand the same morning, and that
asymmetry was the bug.

Three things worth pinning beyond "it saves":

  * BOTH summary paths have to expose `won_at`. The fast one selects NAMED json paths rather than the
    blob, so a key nobody names reaches no card — the projection is executed below against a fake
    that honours the select, not merely grepped.
  * a SENT project needs the mark too, and needs it most: a verbal yes almost always arrives on a
    proposal the customer already has. The portal has no column for it, so the pipeline merge stamps
    it onto the portal's own rows the way `bid_total` is stamped.
  * LOST STILL BEATS WON. The two facts are stored independently on purpose (see drafts.set_won), so
    the precedence lives in the predicates — where it has to live anyway, because a sent project's
    closed_lost belongs to the portal and no draft-side write can clear it.
"""
import importlib
import json
import pathlib
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import drafts
import main

client = TestClient(main.app)
drafts = importlib.import_module("drafts")

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = ROOT / "frontend" / "js" / "crm-core.js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")


def _seed(fake_supabase, data=None):
    store = {"drafts": [
        {"id": "a", "data": data if data is not None else {"project_name": "Nearman Creek"},
         "owner_email": "u@x.com", "created_at": "2026-01-01", "updated_at": "2026-01-02",
         "deleted_at": None},
    ], "events": []}
    return fake_supabase(store), store


# ── A. the store ─────────────────────────────────────────────────────────────
def test_it_records_when_it_was_won_and_who_said_so(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_won("a", True, "hanz@wetreadwell.com") is True
    won = store["drafts"][0]["data"]["won"]
    assert won["by"] == "hanz@wetreadwell.com"
    assert won["at"], "no timestamp, so nothing downstream can tell a marked job from an unmarked one"


def test_marking_it_won_logs_an_event(fake_supabase, monkeypatch):
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_won("a", True, "hanz@wetreadwell.com")
    ev = [e for e in store["events"] if e["action"] == "won"]
    assert len(ev) == 1
    assert ev[0]["detail"]["project_name"] == "Nearman Creek"
    assert ev[0]["actor_email"] == "hanz@wetreadwell.com"


def test_clearing_it_removes_the_key_and_logs_that_too(fake_supabase, monkeypatch):
    """Removing the key rather than storing `{"at": null}` matters: every reader — the two
    summaries, the pipeline merge and isWon — tests the stamp's presence."""
    fake, store = _seed(fake_supabase, {"project_name": "Nearman Creek",
                                        "won": {"at": "2026-08-01", "by": "kyle@x.com"}})
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_won("a", False, "hanz@wetreadwell.com") is True
    assert "won" not in store["drafts"][0]["data"]
    assert [e for e in store["events"] if e["action"] == "not_won"]


def test_marking_it_won_does_not_reorder_the_projects_list(fake_supabase, monkeypatch):
    """Same rule as assigning, picking recipients and closing lost: recording an outcome is not work
    on the estimate, and shuffling the project to the top of a list sorted by date-updated would be
    backwards."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_won("a", True)
    assert store["drafts"][0]["updated_at"] == "2026-01-02"
    drafts.set_won("a", False)
    assert store["drafts"][0]["updated_at"] == "2026-01-02", "clearing the mark bumped it instead"


def test_it_keeps_the_rest_of_the_blob(fake_supabase, monkeypatch):
    """Read-modify-write. The estimate has to survive both directions, or a mis-click loses the
    numbers."""
    fake, store = _seed(fake_supabase)
    store["drafts"][0]["data"]["proposal_lump_sum"] = 41500
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_won("a", True)
    assert store["drafts"][0]["data"]["proposal_lump_sum"] == 41500
    drafts.set_won("a", False)
    assert store["drafts"][0]["data"]["proposal_lump_sum"] == 41500


def test_neither_writer_touches_the_others_key(fake_supabase, monkeypatch):
    """The independence decision, in one test. Popping `closed_lost` here would be a SECOND
    lost-beats-won rule that can only agree with the predicates' one by accident — and it cannot be
    complete anyway, because a SENT project's closed_lost lives in the portal, which these functions
    cannot see. So the store records two independent facts and every reader asks isLost first."""
    fake, store = _seed(fake_supabase, {"project_name": "N",
                                        "closed_lost": {"reason": "timing", "at": "2026-08-01"}})
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_won("a", True)
    assert store["drafts"][0]["data"]["closed_lost"]["reason"] == "timing", (
        "marking a bid won destroyed the reason it was recorded as lost for")
    drafts.set_close_lost("a", "price")
    assert store["drafts"][0]["data"]["won"], "closing it lost destroyed the won mark"


def test_marking_it_won_is_not_archiving(fake_supabase, monkeypatch):
    """Archiving HIDES a project. A won job is the last thing that should vanish off the board."""
    fake, store = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    drafts.set_won("a", True)
    assert store["drafts"][0]["data"].get("archived") in (None, False)


def test_an_unknown_project_says_so(fake_supabase, monkeypatch):
    fake, _ = _seed(fake_supabase)
    monkeypatch.setattr(drafts, "get_client", lambda: fake)
    assert drafts.set_won("nope", True) is False
    assert drafts.set_won("nope", False) is False


# ── B. both summary paths carry it out ───────────────────────────────────────
def test_the_full_blob_summary_exposes_the_stamp():
    s = drafts._summary({"id": "a", "data": {
        "project_name": "Nearman Creek", "won": {"at": "2026-08-19T15:00:00+00:00", "by": "h@x"}}})
    assert s["won_at"] == "2026-08-19T15:00:00+00:00"


def test_a_project_nobody_marked_reports_none_not_a_blank():
    """`or None` is what stops an empty object from producing a truthy value: isWon reads this
    field's truthiness, so `{}` arriving as `{}` would call every project won."""
    assert drafts._summary({"id": "a", "data": {"project_name": "Live"}})["won_at"] is None
    assert drafts._summary({"id": "a", "data": {"won": {}}})["won_at"] is None


# The fast path's projection, EXECUTED. `_build_summaries` selects named json paths rather than the
# blob, so the only way a field reaches a card is by being named in that string — and asserting the
# string contains it proves the string, not the summary. This fake honours the select the way
# PostgREST does, so a field dropped from `cols` comes back absent from the summary here too. That
# exact mistake (a key on the slow path only) cost a fix earlier the same day.
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
    """`data->won->>at` against a Python row, keeping PostgREST's text/object distinction: the LAST
    operator decides, `->>` yielding text (booleans included, which is why `is_test` arrives as
    "true") and `->` yielding the object itself."""
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


def test_the_fast_projection_carries_the_stamp_to_the_card(monkeypatch):
    """The one that matters. Executed through the projection, so dropping `won_at` from `cols` fails
    here rather than only on somebody's screen."""
    store = {"drafts": [{"id": "d1", "owner_email": "k@x.com", "deleted_at": None,
                         "created_at": "2026-08-01", "updated_at": "2026-08-02",
                         "data": {"project_name": "Nearman Creek",
                                  "generate_result": {"work_type": "epoxy"},
                                  "won": {"at": "2026-08-19T15:00:00+00:00", "by": "h@x"}}}]}
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    got = drafts._build_summaries(trashed=False, limit=10)
    assert len(got) == 1, "the fake projection broke the read; fix the fake, not the assertion"
    assert got[0]["won_at"] == "2026-08-19T15:00:00+00:00", (
        "the fast path drops the Won mark, so a marked project reads as Active on every real page "
        "load — the fallback path only runs when PostgREST refuses the select")


def test_the_fast_projection_still_answers_none_for_an_unmarked_project(monkeypatch):
    store = {"drafts": [{"id": "d1", "owner_email": "k@x.com", "deleted_at": None,
                         "created_at": "2026-08-01", "updated_at": "2026-08-02",
                         "data": {"project_name": "Live"}}]}
    monkeypatch.setattr(drafts, "get_client", lambda: _ProjectingClient(store))
    assert drafts._build_summaries(trashed=False, limit=10)[0]["won_at"] is None


def test_the_two_shapers_agree_about_the_field_name():
    """One reads a jsonb scalar, the other a parsed dict. A card's Won state must not depend on
    which read path served the request."""
    slow = drafts._summary({"id": "x", "data": {"won": {"at": "2026-08-19"}}})
    assert "won_at" in slow
    fast = _block_py("_build_summaries")
    assert "won_at:data->won->>at" in fast, "the projection names something else"
    assert '"won_at": r.get("won_at") or None' in fast


def _block_py(fn, module="drafts"):
    src = (ROOT / "backend" / ("%s.py" % module)).read_text(encoding="utf-8")
    lines = src.splitlines()
    start = next(i for i, l in enumerate(lines) if re.match(r"\s*def %s\s*\(" % fn, l))
    indent = len(lines[start]) - len(lines[start].lstrip())
    end = start + 1
    while end < len(lines) and (not lines[end].strip()
                                or (len(lines[end]) - len(lines[end].lstrip())) > indent):
        end += 1
    return "\n".join(lines[start:end])


# ── C. the board rows ────────────────────────────────────────────────────────
def _summary_row(**kw):
    s = {"id": "d1", "project_name": "Nearman Creek", "has_files": True,
         "updated_at": "2026-08-10", "total": 41250}
    s.update(kw)
    return s


def test_a_synthesised_not_sent_row_carries_the_stamp():
    r = main._not_sent_rows([_summary_row(won_at="2026-08-19T15:00:00+00:00")], [])[0]
    assert r["won_at"] == "2026-08-19T15:00:00+00:00", (
        "the mark does not reach the card, so pressing the button appears to do nothing")


def test_an_unmarked_not_sent_row_says_nothing():
    """None, not a stamp. isWon reads truthiness, so any value here would call every unsent bid
    won."""
    assert main._not_sent_rows([_summary_row()], [])[0]["won_at"] is None


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
    """The half that matters most. Hanz's case is a verbal yes, which almost always lands on a
    proposal the customer already has — the portal row has no such column, so without this merge the
    feature would only work in the one column it is least needed in."""
    _wire(monkeypatch, [_portal_row("d1")],
          [_summary_row(id="d1", won_at="2026-08-19T15:00:00+00:00")])
    out = _pipeline()
    assert len(out) == 1, "the sent row was duplicated as a not-sent card"
    assert out["d1"]["won_at"] == "2026-08-19T15:00:00+00:00"


def test_a_sent_project_nobody_marked_gets_no_such_field(monkeypatch):
    """Not `won_at: null` on every row on the board. The portal has no such column, and inventing an
    empty one would claim we had looked."""
    _wire(monkeypatch, [_portal_row("d1")], [_summary_row(id="d1")])
    assert "won_at" not in _pipeline()["d1"]


def test_the_stamp_survives_a_project_the_drafts_list_has_never_heard_of(monkeypatch):
    """Same posture as the test flag and the bid: an unmatched portal row is left ALONE rather than
    stamped with a null, and one unreadable draft must not cost the board."""
    _wire(monkeypatch, [_portal_row("d1"), _portal_row("d2")],
          [_summary_row(id="d1", won_at="2026-08-19T15:00:00+00:00")])
    out = _pipeline()
    assert out["d1"]["won_at"] == "2026-08-19T15:00:00+00:00"
    assert "won_at" not in out["d2"]


# ── D. the endpoint ──────────────────────────────────────────────────────────
def _api(monkeypatch, seen):
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.drafts, "set_won",
                        lambda pid, won, actor: (seen.append((pid, won, actor)), True)[1])
    # `note` is keyword-only in practice — the route passes it by name — and it arrived on
    # 2026-08-20 with the required comment. Spelled out here rather than swallowed by `*a`, so a
    # route that stopped forwarding it fails in this file too.
    monkeypatch.setattr(main.drafts, "set_close_lost",
                        lambda pid, reason, actor, note=None:
                        (seen.append((pid, reason, actor)), True)[1])
    monkeypatch.setattr(main.drafts, "clear_outcome",
                        lambda pid, actor: (seen.append((pid, "CLEARED", actor)), True)[1])
    # `bring_back` asks whether the project was ever sent before deciding to forward `active` to
    # the portal. Stubbed to "never sent", so the second leg is out of this file's way — the
    # forwarding is test_not_sent_lost.py's and test_bring_back's business, not the won mark's.
    monkeypatch.setattr(main.drafts, "latest_revision_no", lambda pid: None)


def test_the_route_marks_it_won(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status", json={"status": "won"})
    assert r.status_code == 200, r.text
    assert seen == [("d1", True, "hanz@wetreadwell.com")]
    assert r.json()["status"] == "won"


def test_the_route_clears_it(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    r = client.post("/api/draft/d1/status", json={"status": "not_won"})
    assert r.status_code == 200, r.text
    assert seen == [("d1", False, "hanz@wetreadwell.com")]
    assert r.json()["status"] == "not_won"


def test_winning_needs_no_approval_and_no_reason(monkeypatch):
    """Decided up front: the mark works whatever the customer has clicked, and there is no
    vocabulary of ways to win. A stray reason riding along must not turn it into a 422."""
    seen = []
    _api(monkeypatch, seen)
    assert client.post("/api/draft/d1/status",
                       json={"status": "won", "reason": "vibes"}).status_code == 200
    assert seen == [("d1", True, "hanz@wetreadwell.com")]


def test_clearing_won_is_not_the_same_call_as_reopening_a_lost_bid(monkeypatch):
    """The clearing-status decision, pinned. `active` is the narrow reopen and must not also erase a
    won mark: one call doing both would write the blob twice and log a "reactivated" event for a
    project nobody had ever closed. `not_won` is the other narrow one, and does not reopen.

    THE COMBINED CLEAR IS A THIRD STATUS, `bring_back`, added 2026-08-20 (Hanz: "there should be an
    option to bring it back to its latest step in the CRM"). It exists because a job marked won and
    THEN closed lost reads as Lost only, so an undo that clears one mark leaves the card on the
    other tab. That is one act and one write — drafts.clear_outcome — which is why it shows up here
    as neither set_won nor set_close_lost. The two narrow undos stay: each says what it undid."""
    seen = []
    _api(monkeypatch, seen)
    client.post("/api/draft/d1/status", json={"status": "active"})
    assert seen == [("d1", None, "hanz@wetreadwell.com")], (
        "reopening a lost bid also went through set_won")
    seen.clear()
    client.post("/api/draft/d1/status", json={"status": "not_won"})
    assert seen == [("d1", False, "hanz@wetreadwell.com")], (
        "clearing the won mark also reopened a bid nobody had closed")
    seen.clear()
    client.post("/api/draft/d1/status", json={"status": "bring_back"})
    assert seen == [("d1", "CLEARED", "hanz@wetreadwell.com")], (
        "bringing a bid back went through one of the narrow undos, so the other mark survives")


def test_a_status_nobody_defined_is_refused(monkeypatch):
    seen = []
    _api(monkeypatch, seen)
    for junk in ("winner", "won_maybe", "unwon", ""):
        assert client.post("/api/draft/d1/status",
                           json={"status": junk}).status_code == 422, junk
    assert seen == []


def test_a_missing_project_is_a_404(monkeypatch):
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")
    monkeypatch.setattr(main.drafts, "set_won", lambda *a: False)
    assert client.post("/api/draft/gone/status", json={"status": "won"}).status_code == 404


def test_a_store_failure_does_not_claim_success(monkeypatch):
    """The drawer repaints itself as won on `ok`. A 200 over a failed write would show a Won chip
    that no database agrees with, and the next board poll would take it away again."""
    monkeypatch.setattr(main, "_user_email", lambda request: "hanz@wetreadwell.com")

    def boom(*a):
        raise RuntimeError("postgrest down")
    monkeypatch.setattr(main.drafts, "set_won", boom)
    assert client.post("/api/draft/d1/status", json={"status": "won"}).status_code == 502


# ── E. the predicate, run for real ───────────────────────────────────────────
@pytest.fixture(scope="module")
def verdicts():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    rows = {
        # marked by hand, and NOTHING else true of it: not sent, not approved, no deposit
        "manual": {"proposal_status": "sent", "won_at": "2026-08-19T15:00:00+00:00"},
        "manual_unsent": {"not_sent": True, "won_at": "2026-08-19T15:00:00+00:00"},
        # the derived rule, both ways it can be satisfied
        "derived_paid": {"proposal_status": "approved", "deposit_status": "received"},
        "derived_nodeposit": {"approved_at": "2026-08-01", "deposit_required": False},
        # approved with the money still out: the most worth-chasing row there is
        "approved_owing": {"proposal_status": "approved", "deposit_requested_at": "2026-08-02",
                           "deposit_status": "requested"},
        "plain_sent": {"proposal_status": "sent"},
        # marked won and then closed lost anyway
        "manual_then_lost": {"proposal_status": "closed_lost",
                             "won_at": "2026-08-19T15:00:00+00:00"},
        # marked won, then re-sent as a revision. A revision must not un-win it.
        "manual_resent": {"proposal_status": "sent", "sent_at": "2026-08-20T09:00:00+00:00",
                          "last_activity_at": "2026-08-20T09:00:00+00:00",
                          "won_at": "2026-08-19T15:00:00+00:00"},
        "manual_test": {"proposal_status": "sent", "is_test": True,
                        "won_at": "2026-08-19T15:00:00+00:00"},
        "cleared": {"proposal_status": "sent", "won_at": ""},
    }
    src = ("const C = require(%s);\nconst R = %s;\nconst o = {};\n"
           "for (const k of Object.keys(R)) o[k] = { won: C.isWon(R[k]), lost: C.isLost(R[k]),\n"
           "  byHand: C.wonByHand(R[k]), test: C.isTest(R[k]), stage: C.stage(R[k]) };\n"
           "console.log(JSON.stringify(o));\n" % (json.dumps(str(CORE)), json.dumps(rows)))
    out = subprocess.run(["node", "-e", src], capture_output=True, text=True,
                         encoding="utf-8", timeout=60)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


@needs_node
def test_a_hand_marked_project_is_won_with_nothing_else_true_of_it(verdicts):
    """The whole ask. Neither half of the derived rule holds on these two rows — one was never even
    sent — and both have to read as won, or the button is decoration."""
    assert verdicts["manual"]["won"] is True
    assert verdicts["manual_unsent"]["won"] is True


@needs_node
def test_the_derived_rule_still_stands_on_its_own(verdicts):
    """The mark is an override, not a replacement. Every job that was won before this feature
    existed has no stamp, and must not fall out of Won the day it ships."""
    assert verdicts["derived_paid"]["won"] is True
    assert verdicts["derived_nodeposit"]["won"] is True
    assert verdicts["approved_owing"]["won"] is False, (
        "an approved job with the deposit outstanding is being called won, which hides the most "
        "worth-chasing project there is from the person whose job is the chasing")
    assert verdicts["plain_sent"]["won"] is False


@needs_node
def test_lost_still_beats_won(verdicts):
    """A job won on the phone and cancelled a week later is LOST. Nothing in isWon checks isLost —
    the precedence lives in every reader (stage, ppCategory, chipsHtml), because a sent project's
    closed_lost belongs to the portal and no draft-side write can clear it."""
    v = verdicts["manual_then_lost"]
    assert v["won"] is True, "fixture drift: this row is supposed to be one Won would claim"
    assert v["lost"] is True
    assert v["stage"] == "Closed lost", (
        "the board would keep a cancelled job on its live columns because somebody had marked it won")


@needs_node
def test_a_test_project_can_be_marked_won_and_is_still_a_test_project(verdicts):
    """The mark says nothing about whether the project is real work. Test beats Won on the
    notification page for that reason, and the flag has to survive to get there."""
    assert verdicts["manual_test"]["won"] is True
    assert verdicts["manual_test"]["test"] is True


@needs_node
def test_a_re_send_does_not_un_win_it(verdicts):
    """Decided up front: the mark is deliberate, and a revision is not a customer changing their
    mind. Nothing about sending clears `won_at`, so the only thing that can is the undo button."""
    assert verdicts["manual_resent"]["won"] is True
    assert verdicts["manual_resent"]["stage"] == "Sent", "fixture drift"


@needs_node
def test_undoing_the_mark_puts_it_back_in_the_working_list(verdicts):
    """The optimistic patch clears the field with `""` rather than deleting it, so the falsey branch
    has to be the one that answers."""
    assert verdicts["cleared"]["won"] is False
    assert verdicts["cleared"]["byHand"] is False


@needs_node
def test_by_hand_is_distinguishable_from_won_anyway(verdicts):
    """The drawer needs the difference: there is nothing to undo about a deposit that arrived, and an
    "Undo won" button on a paid job would appear to do nothing."""
    assert verdicts["manual"]["byHand"] is True
    assert verdicts["derived_paid"]["byHand"] is False
    assert verdicts["derived_paid"]["won"] is True


@needs_node
def test_won_is_still_defined_once_for_both_screens():
    """The reason it moved to crm-core on 2026-08-19. A local copy on either page is how "won"
    starts meaning two things again — this time with a manual override to disagree about."""
    core = CORE.read_text(encoding="utf-8")
    assert "function isWon" in core and "isWon: isWon" in core
    for page in ("portal.js", "notifications.js"):
        js = (ROOT / "frontend" / "js" / page).read_text(encoding="utf-8")
        assert "function isWon" not in js, "%s has its own copy of isWon" % page
        assert "isWon" in js, "%s does not use the shared isWon at all" % page
