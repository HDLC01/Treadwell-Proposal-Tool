"""The Estimating Tool v2 board (BETA): its own route, its own code, separate from the real boards.

Built 2026-10-13 on the v2 Estimates page. Moved 2026-10-15 to /v2-board.html, the page the Estimating
Tool v2 sidebar row opens (Hanz: "It should be here not V2 estimates"; v2 Estimates is a list again,
test_v2_names.py), and given the Direct Projects card buttons (Hanz: "Yes, same buttons").

Hanz, 2026-10-13: "make the V2 have a pipeline like the ones we have for active projects", "make sure
they are separate tho", then "the V2 pipeline is still in beta ... so do not merge it to the
existing". So the board is built as NEW code that reads the shared, DOM-free crm-core.js, and the
existing boards (portal.js, portal.html, /gc-projects.html, notifications.js and the
/api/portal/pipeline route) are not touched.

WHAT HAS TO HOLD
  A. /api/v2/pipeline returns v2 (polish_beta) drafts and only those, from creation, test copies
     included, and TWCrm.stage files each one in the right column.
  B. THE REAL BOARDS STAY SEPARATE: the default /api/portal/pipeline answer for a mixed fixture is
     what it has always been (no v2 field, and a never-generated v2 draft is still not on it), the
     real board files mention nothing from the v2 board, and the v2 board never loads portal.js.
     Nothing here freezes the source of those files, so an unrelated edit to them is free to land.
  B2. THE FEED HAS THE SAME DOOR AS THE PAGE: /api/v2/pipeline is claimed by the Estimating Tool v2
     tab in nav_access, so a member who is denied the page gets 403 from the route and one who is not
     gets the data.
  C. SEPARATE STORAGE: every key the board writes starts tw_v2_; seeding the real boards' keys
     changes nothing it reads; localStorage is never touched (the harness throws if it is) except by
     "+ New", which clears the three keys every "start a project" door clears.
  D. THE PANEL STAYS FACTS: it carries no send, follow-up, deposit, chat or status control, and the
     page's code, executed, makes exactly one GET (to its own feed) however it is walked, as long as
     nobody presses a card button.
  D2. THE CARD BUTTONS ARE THE DIRECT PROJECTS ONES: same labels, same rule for which shows, and,
     pressed for real, the same requests to the same routes, with the same close-out dialog and
     hand-off prompt in front of them. "+ New" starts a fresh bid in the intake.
  E. THE PAGE: Direct and GC tabs by audience, test copies on the board with a chip, no price is a
     dash and never $0, search kept, month and sort gone. It says so when the customer portal is
     stale or down, and "v2 total" is only ever what v2 priced.
  F. HOSTILE TEXT: a name, email or id with markup in it comes out as plain text everywhere.

Everything JavaScript here is EXECUTED (tests/js/v2-board-harness.js), not read as source text.
"""
import inspect
import json
import pathlib
import re
import tempfile
from datetime import datetime, timezone
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

import main
import nav_access
import v2_pipeline
from _node import last_json_line, run_node

client = TestClient(main.app)
ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "v2-board-harness.js"


# ── reading markup with a parser, never a pattern ────────────────────────────
class Markup(HTMLParser):
    """Walks a fragment of HTML and keeps what a person (or a browser) would act on: the text, every
    tag, every attribute. `skip(tag, attrs)` names an element to leave out whole, children included.
    Comments are not words and <style>/<script> bodies are not words, so none of them reach `text`.

    A regular expression is the wrong tool for any of this: a pattern that strips tags or comments
    in one pass can be walked around, and one that is wrong fails by looking at the wrong text."""

    def __init__(self, skip=None, attrs_as_text=False):
        super().__init__(convert_charrefs=True)
        self._skip = skip or (lambda tag, attrs: False)
        self._attrs_as_text = attrs_as_text      # placeholder="..." and title="..." are read by people too
        self._dropping = None        # [tag, depth] while inside a dropped element
        self._code = 0               # depth inside <style> / <script>
        self.chunks, self.tags, self.attrs = [], [], []

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._code += 1
            return
        if self._dropping:
            if tag == self._dropping[0]:
                self._dropping[1] += 1
            return
        if self._skip(tag, dict(attrs)):
            self._dropping = [tag, 1]
            return
        self.tags.append(tag)
        for name, value in attrs:
            self.attrs.append((tag, name, value))
            if value and self._attrs_as_text:
                self.chunks.append(value)

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._code = max(0, self._code - 1)
        elif self._dropping and tag == self._dropping[0]:
            self._dropping[1] -= 1
            if not self._dropping[1]:
                self._dropping = None

    def handle_data(self, data):
        if not self._code and not self._dropping:
            self.chunks.append(data)

    @property
    def text(self):
        return " ".join(self.chunks)


def markup(html, skip=None, attrs_as_text=False):
    m = Markup(skip, attrs_as_text)
    m.feed(html)
    m.close()
    return m


# ── fixtures ─────────────────────────────────────────────────────────────────
def _draft(did, **kw):
    base = {"id": did, "project_name": "Job " + did, "has_files": False, "archived": False,
            "is_test": True, "polish_beta": True, "owner_email": "kyle@wetreadwell.com",
            "assigned_estimator": None, "contact_email": "", "total": 12500, "audience": "Direct",
            "updated_at": "2026-10-10T15:00:00+00:00", "work_type": "polish", "sent_revision": 0,
            "won_at": None, "handed_off_at": None}
    base.update(kw)
    return base


def _portal_row(pid, **kw):
    base = {"proposal_id": pid, "project_name": "Job " + pid, "customer_email": "c@x.com",
            "proposal_status": "viewed", "deposit_status": "pending", "contacts_status": "pending",
            "unread": 0, "sent_at": "2026-10-09T12:00:00+00:00",
            "estimator_email": "kyle@wetreadwell.com"}
    base.update(kw)
    return base


DRAFTS = [
    _draft("v-fresh"),                                                  # never generated
    _draft("v-gc", audience="GC", has_files=True),
    _draft("v-test-real", is_test=False, project_name="Real v2 bid"),    # not a test copy
    _draft("v-unpriced", total=None),
    _draft("v-won", won_at="2026-10-11T09:00:00+00:00"),
    _draft("v-viewed"),                                                 # the portal has it
    _draft("v-deposit"),                                                # deposit landed
    _draft("v-lost", closed_lost_reason="price", closed_lost_at="2026-10-11T10:00:00+00:00"),
    _draft("v-handed", handed_off_at="2026-10-12T10:00:00+00:00"),
    _draft("v-archived", archived=True),
    _draft("real-1", polish_beta=False, is_test=False, has_files=True, total=40000),
    _draft("real-2", polish_beta=False, is_test=False, has_files=False),
]
PORTAL = [
    _portal_row("v-viewed"),
    _portal_row("v-deposit", proposal_status="approved", deposit_status="received",
                approved_total=13000),
    _portal_row("real-1"),
    _portal_row("someone-else-entirely"),
]


@pytest.fixture(autouse=True)
def cold_cache():
    main._PIPELINE_CACHE.update({"rows": None, "fetched_at": None})
    yield
    main._PIPELINE_CACHE.update({"rows": None, "fetched_at": None})


def _up(monkeypatch, drafts=DRAFTS, portal=PORTAL):
    monkeypatch.setattr(main, "_portal", lambda p, m="GET", b=None: {"ok": True, "proposals": portal})
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: drafts)


def _v2(monkeypatch, **kw):
    _up(monkeypatch, **kw)
    r = client.get("/api/v2/pipeline")
    assert r.status_code == 200, r.text
    return r.json()


def _by_id(body):
    return {p["proposal_id"]: p for p in body["proposals"]}


# ═════════════════════════════════════════════════════════════════════════════
# A. the endpoint
# ═════════════════════════════════════════════════════════════════════════════
def test_the_endpoint_returns_v2_drafts_and_only_those(monkeypatch):
    body = _v2(monkeypatch)
    ids = {p["proposal_id"] for p in body["proposals"]}
    assert ids == {"v-fresh", "v-gc", "v-test-real", "v-unpriced", "v-won", "v-viewed", "v-deposit",
                   "v-lost", "v-handed"}
    # a real project, an archived v2 draft and a portal row nobody here owns never appear
    assert not ids & {"real-1", "real-2", "v-archived", "someone-else-entirely"}
    assert all(p["v2"] is True for p in body["proposals"])
    assert body["ok"] is True and body["read_ceiling"] == 300


def test_a_started_v2_bid_is_a_card_from_creation_and_test_copies_are_included(monkeypatch):
    rows = _by_id(_v2(monkeypatch))
    fresh = rows["v-fresh"]
    assert fresh["not_sent"] is True and fresh["is_test"] is True
    assert rows["v-test-real"]["is_test"] is False


def test_a_v2_card_is_stamped_with_its_board_by_audience(monkeypatch):
    rows = _by_id(_v2(monkeypatch))
    assert rows["v-gc"]["pipeline"] == "gc" and rows["v-fresh"]["pipeline"] == "direct"


def test_the_portals_row_wins_for_a_v2_bid_it_knows_and_a_real_ones_never_leaks(monkeypatch):
    rows = _by_id(_v2(monkeypatch))
    assert rows["v-deposit"]["deposit_status"] == "received" and "not_sent" not in rows["v-deposit"]
    assert rows["v-deposit"]["approved_total"] == 13000
    assert rows["v-viewed"]["bid_total"] == 12500     # our figure fills a null, never replaces one
    # what v2 itself priced rides beside the portal's figures and is never one of them
    assert rows["v-deposit"]["v2_total"] == 12500 and rows["v-fresh"]["v2_total"] == 12500
    assert rows["v-unpriced"]["v2_total"] is None


def test_an_archived_v2_bid_stays_when_the_portal_has_it_and_goes_when_it_does_not(monkeypatch):
    """Parity with the real board, which drops an archived draft only when nothing was sent: a bid
    the customer has is live work, whatever the Proposals Database says about its filing."""
    drafts = [_draft("arch-sent", archived=True, has_files=True, sent_revision=1),
              _draft("arch-never", archived=True),
              _draft("live-one")]
    portal = [_portal_row("arch-sent", proposal_status="sent")]
    body = _v2(monkeypatch, drafts=drafts, portal=portal)
    ids = {p["proposal_id"] for p in body["proposals"]}
    assert ids == {"arch-sent", "live-one"}
    real = {p["proposal_id"] for p in client.get("/api/portal/pipeline").json()["proposals"]}
    assert "arch-sent" in real and "arch-never" not in real       # the real board does the same
    # the portal down and nothing cached: neither board invents a card for an archived draft
    main._PIPELINE_CACHE.update({"rows": None, "fetched_at": None})

    def boom(*a, **k):
        raise main.HTTPException(502, "down")
    monkeypatch.setattr(main, "_portal", boom)
    ids = {p["proposal_id"] for p in client.get("/api/v2/pipeline").json()["proposals"]}
    real = {p["proposal_id"] for p in client.get("/api/portal/pipeline").json()["proposals"]}
    assert ids == {"live-one"} and "arch-sent" not in real


def test_the_feed_says_how_old_the_portals_answer_is(monkeypatch):
    live = _v2(monkeypatch)
    assert live["portal_status"] == "live" and isinstance(live["portal_fetched_at"], float)
    stamp = live["portal_fetched_at"]

    def boom(*a, **k):
        raise main.HTTPException(502, "down")
    monkeypatch.setattr(main, "_portal", boom)
    stale = client.get("/api/v2/pipeline").json()
    assert stale["portal_status"] == "stale" and stale["portal_fetched_at"] == stamp
    main._PIPELINE_CACHE.update({"rows": None, "fetched_at": None})
    offline = client.get("/api/v2/pipeline").json()
    assert offline["portal_status"] == "offline" and offline["portal_fetched_at"] is None


def test_a_portal_outage_files_a_sent_v2_bid_as_unknown_not_as_unsent(monkeypatch):
    def boom(*a, **k):
        raise main.HTTPException(502, "down")
    monkeypatch.setattr(main, "_portal", boom)
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: [
        _draft("sent-one", has_files=True, sent_revision=2), _draft("never-sent")])
    body = client.get("/api/v2/pipeline").json()
    rows = _by_id(body)
    assert body["portal_status"] == "offline"
    assert rows["sent-one"].get("portal_unknown") is True and "not_sent" not in rows["sent-one"]
    assert rows["never-sent"]["not_sent"] is True


def test_an_unreadable_drafts_list_is_a_failure_and_not_an_empty_board(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(main.drafts, "list_drafts", boom)
    body = client.get("/api/v2/pipeline").json()
    assert body["ok"] is False and body["proposals"] == []


def test_the_endpoint_writes_nothing(monkeypatch):
    """It reads the drafts list and the portal snapshot; no draft, status or portal write is reachable
    from it (any attempt would hit these and fail the test)."""
    _up(monkeypatch)
    for name in ("save_draft", "set_won", "set_handed_off", "set_close_lost", "set_on_hold",
                 "assign_draft", "trash_draft", "archive_draft"):
        if hasattr(main.drafts, name):
            monkeypatch.setattr(main.drafts, name,
                                lambda *a, **k: pytest.fail("the v2 board wrote a draft"))
    assert client.get("/api/v2/pipeline").status_code == 200
    src = inspect.getsource(v2_pipeline) + inspect.getsource(main.api_v2_pipeline)
    assert "_portal(" not in inspect.getsource(v2_pipeline)
    assert not re.search(r"\.(post|put|patch|delete)\(|requests\.|httpx\.", src)


# ═════════════════════════════════════════════════════════════════════════════
# B. the real boards are unchanged
# ═════════════════════════════════════════════════════════════════════════════
# What keeps the boards apart is BEHAVIOUR, not a frozen copy of their source. Three things are held:
# the real board's default answer (the golden below), the real board files naming nothing from the v2
# board, and the v2 board never loading portal.js. An unrelated edit to portal.js or to the real
# route is free to land; one that reaches into v2, or changes what the real board answers, fails.
@pytest.mark.parametrize("name", ["js/portal.js", "portal.html", "js/notifications.js"])
def test_the_real_boards_know_nothing_about_v2(name):
    text = (FRONTEND / name).read_text(encoding="utf-8")
    for token in ("tw_v2_", "/api/v2/", "v2-board", "TWV2Board"):
        assert token not in text, "%s mentions %s" % (name, token)


def test_the_v2_code_never_loads_or_calls_portal_js():
    html = (FRONTEND / "v2-board.html").read_text(encoding="utf-8")
    assert "/js/portal.js" not in html and "/js/v2-board.js" in html
    for name in ("v2-board.js", "v2-board-core.js"):
        code = (FRONTEND / "js" / name).read_text(encoding="utf-8")
        assert not re.search(r"""require\(["'][^"']*portal""", code)
    route = inspect.getsource(main.api_portal_pipeline)
    assert "v2_pipeline" not in route and "polish_beta" not in route


def test_the_default_pipeline_answer_is_exactly_what_it_was(monkeypatch):
    """GOLDEN. A mixed fixture through the REAL route: a v2 draft that was never generated is still
    not on the real board, nothing carries a v2 stamp, and the rows are the ones the route has always
    built (the pre-existing behaviour for a generated v2 draft is also unchanged)."""
    _up(monkeypatch)
    body = client.get("/api/portal/pipeline").json()
    rows = _by_id(body)
    assert "v-fresh" not in rows and "v-unpriced" not in rows        # never generated: not on it
    assert "v2" not in json.dumps(body)
    assert sorted(rows) == sorted(["v-viewed", "v-deposit", "real-1", "someone-else-entirely", "v-gc"])
    assert rows["real-1"]["bid_total"] == 40000 and rows["real-1"]["pipeline"] == "direct"
    assert rows["v-gc"]["not_sent"] is True and rows["v-gc"]["pipeline"] == "gc"
    assert set(body) == {"proposals", "portal_status", "portal_fetched_at"}


# ── B2. the feed has the same door as the page ───────────────────────────────
@pytest.fixture
def policy(tmp_path, monkeypatch):
    """A nav policy file per test (the real one lives on the data volume) and no cached profile."""
    monkeypatch.setattr(nav_access, "_FILE", tmp_path / "nav_access.json")
    monkeypatch.setattr(nav_access, "_DATA_DIR", tmp_path)
    main._profile_cache_clear()
    yield nav_access
    main._profile_cache_clear()


def _signed_in_as(monkeypatch, role, email="staffer@wetreadwell.com"):
    """A client whose role is resolved the way the app resolves it, through the profile."""
    monkeypatch.setattr(main, "_user_email", lambda request: email)
    monkeypatch.setattr(main.profiles, "get_by_email",
                        lambda e: {"id": "u1", "email": email, "role": role, "status": "active"})
    main._profile_cache_clear()
    return TestClient(main.app)


def test_a_member_without_the_v2_page_gets_403_from_its_feed_and_one_with_it_gets_the_data(
        monkeypatch, policy):
    _up(monkeypatch)
    policy.save({"user": ["/v2-board.html"]}, "k@x.com")
    # denied the page: the route refuses with the gate's own body, and no draft is read at all
    reads = []
    monkeypatch.setattr(main.drafts, "list_drafts", lambda *a, **k: reads.append(1) or DRAFTS)
    refused = _signed_in_as(monkeypatch, "user").get("/api/v2/pipeline")
    assert refused.status_code == 403
    assert refused.json()["nav_denied"] is True and "proposals" not in refused.json()
    assert reads == [], "a denied member's request reached the drafts list"
    # not denied (a role the policy does not name): the same route answers with the bids
    _up(monkeypatch)
    allowed = _signed_in_as(monkeypatch, "admin").get("/api/v2/pipeline")
    assert allowed.status_code == 200
    assert {p["proposal_id"] for p in allowed.json()["proposals"]} >= {"v-fresh", "v-gc"}
    # and with nothing denied to anyone, a member reads it too
    policy.save({}, "k@x.com")
    assert _signed_in_as(monkeypatch, "user").get("/api/v2/pipeline").status_code == 200


def test_denying_another_tab_leaves_the_v2_feed_open_and_denying_this_one_leaves_the_real_board_open(
        monkeypatch, policy):
    _up(monkeypatch)
    # v2 Estimates is a different row now (a list on /api/drafts): denying it leaves the board's feed
    policy.save({"user": ["/history.html", "/polish-estimates.html", "/projects.html"]}, "k@x.com")
    assert _signed_in_as(monkeypatch, "user").get("/api/v2/pipeline").status_code == 200
    policy.save({"user": ["/v2-board.html"]}, "k@x.com")
    client = _signed_in_as(monkeypatch, "user")
    assert client.get("/api/portal/pipeline").status_code == 200      # the real boards' feed
    assert client.get("/api/drafts").status_code == 200               # the Proposals Database's list


# ═════════════════════════════════════════════════════════════════════════════
# the harness, run once per payload
# ═════════════════════════════════════════════════════════════════════════════
def _run(payload, scenarios):
    with tempfile.TemporaryDirectory() as d:
        inp = pathlib.Path(d) / "in.json"
        inp.write_text(json.dumps({"payload": payload, "scenarios": scenarios}), encoding="utf-8")
        proc = run_node(HARNESS, FRONTEND, inp)
    assert proc.returncode == 0, proc.stderr
    return last_json_line(proc.stdout)


@pytest.fixture
def payload(monkeypatch):
    return _v2(monkeypatch)


def test_every_v2_row_lands_in_the_column_crm_core_says(payload):
    out = _run(payload, [])
    stage = {r["id"]: r["stage"] for r in out["core"]["rows"]}
    assert stage == {
        "v-fresh": "Created but not sent", "v-gc": "Created but not sent",
        "v-test-real": "Created but not sent", "v-unpriced": "Created but not sent",
        "v-won": "Won/Approved",                      # marked won by hand: a column, not a tab
        "v-viewed": "Viewed",
        "v-deposit": "Deposit received",
        "v-lost": "Closed lost", "v-handed": "Created but not sent",
    }
    assert out["core"]["columns"]["direct"] == out["core"]["columns"]["crmStages"]


def test_direct_and_gc_split_by_audience_and_lost_and_handed_off_are_their_own(payload):
    pools = _run(payload, [])["core"]["pools"]
    assert sorted(pools["gc"]) == ["v-gc"]
    assert sorted(pools["direct"]) == ["v-deposit", "v-fresh", "v-test-real", "v-unpriced", "v-viewed",
                                       "v-won"]
    assert pools["lost"] == ["v-lost"] and pools["handed_off"] == ["v-handed"]
    # a partition: every row on exactly one tab
    seen = [i for t in pools.values() for i in t]
    assert sorted(seen) == sorted(p["proposal_id"] for p in payload["proposals"])


def test_lost_and_handed_off_tabs_only_appear_when_they_hold_a_bid(monkeypatch):
    plain = _v2(monkeypatch, drafts=[_draft("only")], portal=[])
    out = _run(plain, [])
    assert out["core"]["tabs"] == ["direct", "gc"]
    out = _run(_v2(monkeypatch), [])
    assert out["core"]["tabs"] == ["direct", "gc", "lost", "handed_off"]


def test_a_test_copy_sits_on_the_board_with_a_test_chip_and_a_real_bid_does_not(payload):
    cards = _run(payload, [])["core"]["cards"]
    assert 'chip-test' in cards["v-fresh"] and "Test</span>" in cards["v-fresh"]
    assert 'chip-test' not in cards["v-test-real"]


def test_no_price_is_a_dash_and_never_zero(payload):
    cards = _run(payload, [])["core"]["cards"]
    assert "&mdash;" in cards["v-unpriced"] and "$0" not in cards["v-unpriced"]
    assert "$12,500" in cards["v-fresh"]
    assert "$13,000" in cards["v-deposit"]            # the portal's approved figure wins


def test_the_panel_calls_a_figure_v2_total_only_when_v2_priced_it(monkeypatch, payload):
    """The card shows the board's figure (the portal's approved total wins), so the panel's "v2 total"
    row must be the draft's own price, and the other figure gets a row that says whose it is."""
    panels = _run(payload, [])["core"]["panels"]
    dep = panels["v-deposit"]
    assert "<dt>v2 total</dt><dd>$12,500</dd>" in dep           # NOT the $13,000 the card shows
    assert "<dt>Approved total</dt><dd>$13,000</dd>" in dep
    # a bid whose board figure IS v2's gets the one row
    for pid in ("v-viewed", "v-fresh"):
        assert "<dt>v2 total</dt><dd>$12,500</dd>" in panels[pid], pid
        assert "Approved total" not in panels[pid] and "Sent total" not in panels[pid], pid
    assert "<dt>v2 total</dt><dd>Not priced yet</dd>" in panels["v-unpriced"]
    # sent at a different figure than v2 priced, not yet approved: "Sent total", never "v2 total"
    edited = _v2(monkeypatch, portal=[], drafts=[_draft("v-edit")])
    edited["proposals"][0].update({"proposal_status": "sent", "bid_total": 11000, "not_sent": False})
    sent = _run(edited, [])["core"]["panels"]["v-edit"]
    assert "<dt>v2 total</dt><dd>$12,500</dd>" in sent and "<dt>Sent total</dt><dd>$11,000</dd>" in sent


# ── the customer portal's health ─────────────────────────────────────────────
STAMP = datetime(2026, 10, 10, 15, 0, tzinfo=timezone.utc).timestamp()


def _with_portal(payload, status, fetched_at):
    return dict(payload, portal_status=status, portal_fetched_at=fetched_at)


def test_the_board_says_so_when_the_portals_answer_is_old_or_missing(payload):
    """Placement is right in every mode (the server decides it); what the page owed was a sentence
    saying the figures may be behind. Said once, outside the board, and gone when the portal is back."""
    html = (FRONTEND / "v2-board.html").read_text(encoding="utf-8")
    assert 'id="v2-degraded" class="v2-degraded" role="status" hidden>' in html
    assert ".v2-degraded[hidden] { display:none; }" in html       # a class display rule outranks [hidden]
    live = _run(_with_portal(payload, "live", STAMP), [{"name": "l", "actions": []}])["runs"][0]["first"]
    assert live["degradedHidden"] is True and live["degraded"] == ""
    stale = _run(_with_portal(payload, "stale", STAMP), [{"name": "s", "actions": []}])["runs"][0]["first"]
    assert stale["degradedHidden"] is False
    assert "Showing the board as of 2026-10-10 15:00." in stale["degraded"]
    assert "customer portal is not responding" in stale["degraded"]
    undated = _run(_with_portal(payload, "stale", None), [{"name": "u", "actions": []}])["runs"][0]["first"]
    assert "Showing the last answer the customer portal gave." in undated["degraded"]
    offline = _run(_with_portal(payload, "offline", None), [{"name": "o", "actions": []}])["runs"][0]["first"]
    assert offline["degradedHidden"] is False
    assert "built from the list this tool keeps" in offline["degraded"]
    assert "Created but not sent" in offline["degraded"]
    # the notice is not part of the board, so a repaint of the columns can never wipe or double it
    assert "not responding" not in offline["list"]
    # and none of it is customer-facing copy with a dash in it (house rule)
    assert "—" not in stale["degraded"] + offline["degraded"] + undated["degraded"]


# ── hostile strings: names, emails and ids come from forms and drafts ────────
HOSTILE_ID = "a\"b'c&d<e>"
HOSTILE_ROWS = [
    _draft(HOSTILE_ID, project_name="<img src=x onerror=window.__xss=1>",
           contact_email="\"><script>window.__xss=2</script>@x.com",
           owner_email="x<u>boss</u>@x.com"),
    _draft("lost-one", project_name="<svg onload=window.__xss=3>", closed_lost_reason="</span><i>why</i>",
           closed_lost_at="2026-10-11T10:00:00+00:00"),
]
# Every tag the board's own markup uses. A hostile string that gets through unescaped shows up as a
# tag outside this set (or an attribute that is not a plain name); if a new tag is added on purpose,
# add it here.
BOARD_TAGS = {"div", "span", "h2", "button", "dl", "dt", "dd", "p", "a", "option", "b"}
PLAIN_ATTR = re.compile(r"^[a-z][a-z0-9-]*$")


def _assert_inert(label, html):
    m = markup(html)
    stray = [t for t in m.tags if t not in BOARD_TAGS]
    assert not stray, (label, stray, html)
    bad = [(t, n) for t, n, _v in m.attrs if not PLAIN_ATTR.match(n) or n.startswith("on")]
    assert not bad, (label, bad, html)


def test_hostile_names_emails_and_ids_come_out_as_plain_text(monkeypatch):
    payload = _v2(monkeypatch, drafts=HOSTILE_ROWS, portal=[])
    out = _run(payload, [{"name": "d", "actions": [{"type": "open", "id": HOSTILE_ID}]},
                         {"name": "l", "actions": [{"type": "tab", "tab": "lost"}]}])
    pieces = {}
    pieces.update({"card " + k: v for k, v in out["core"]["cards"].items()})
    pieces.update({"panel " + k: v for k, v in out["core"]["panels"].items()})
    for run in out["runs"]:
        for where in ("first", "last"):
            for field in ("list", "tabs", "est", "panel"):
                pieces["%s %s %s" % (run["name"], where, field)] = run[where][field]
    assert len(pieces) > 10
    for label, html in pieces.items():
        _assert_inert(label, html)
    # the words themselves arrive, as text
    card = out["core"]["cards"][HOSTILE_ID]
    assert "&lt;img src=x onerror=window.__xss=1&gt;" in card
    # an id in an attribute: quote, apostrophe, ampersand and angle brackets all escaped
    assert 'data-id="a&quot;b&#39;c&amp;d&lt;e&gt;"' in card
    # and in the link: encodeURIComponent leaves an apostrophe alone, so the escape is what covers it
    panel = out["core"]["panels"][HOSTILE_ID]
    assert re.findall(r'href="([^"]*)"', panel) == ["/polish-intake.html?d=a%22b&#39;c%26d%3Ce%3E"]
    assert "x&lt;u&gt;boss" in out["runs"][0]["last"]["est"]       # the estimator menu, label and value


# ── C. separate storage ──────────────────────────────────────────────────────
REAL_BOARD_KEYS = {"tw_crm_tab": "lost", "tw_crm_tab_gc": "lost", "tw_crm_est": "kyle@wetreadwell.com",
                   "tw_crm_est_gc": "nobody@x.com", "tw_crm_month": "2026-01", "tw_crm_view_active": "table",
                   "tw_crm_view_lost": "table", "tw_crm_sortfield": "total", "tw_crm_sortdir": "asc",
                   "tw_projects_filter": "x", "treadwell.proposal_tool.hydrated_once": "1"}
ACTIONS = [{"type": "tab", "tab": "gc"}, {"type": "search", "value": "job"},
           {"type": "est", "value": "kyle@wetreadwell.com"}, {"type": "open", "id": "v-gc"},
           {"type": "close"}, {"type": "clear"}, {"type": "tab", "tab": "direct"}]


def test_every_key_the_board_writes_is_its_own(payload):
    out = _run(payload, [{"name": "walk", "actions": ACTIONS}])["runs"][0]
    assert out["writes"], "the walk wrote nothing, so this proves nothing"
    keys = {k for k, _v in out["writes"]}
    assert keys <= {"tw_v2_tab", "tw_v2_est", "tw_v2_search"}, keys
    assert all(k.startswith("tw_v2_") for k in out["reads"]), out["reads"]


def test_the_real_boards_keys_change_nothing_the_v2_board_reads_or_writes(payload):
    clean = _run(payload, [{"name": "a", "actions": ACTIONS}])["runs"][0]
    seeded = _run(payload, [{"name": "b", "session": REAL_BOARD_KEYS, "actions": ACTIONS}])["runs"][0]
    assert seeded["first"] == clean["first"] and seeded["last"] == clean["last"]
    assert seeded["writes"] == clean["writes"]
    # and the real boards' keys are still exactly as they were, untouched
    for k, v in REAL_BOARD_KEYS.items():
        assert seeded["session"][k] == v


def test_the_tab_search_and_estimator_survive_in_the_v2_keys(payload):
    first = _run(payload, [{"name": "w", "actions": [{"type": "tab", "tab": "gc"},
                                                      {"type": "search", "value": "gc"}]}])["runs"][0]
    resumed = _run(payload, [{"name": "r", "session": first["session"], "actions": []}])["runs"][0]
    assert 'data-tab="gc"' in resumed["first"]["tabs"] and 'aria-pressed="true"' in resumed["first"]["tabs"]
    assert "Job v-gc" in resumed["first"]["list"] and "Job v-fresh" not in resumed["first"]["list"]


# ── E. the page ──────────────────────────────────────────────────────────────
def test_the_board_paints_the_active_projects_columns_and_the_gc_tab_swaps_the_cards(payload):
    run = _run(payload, [{"name": "p", "actions": [{"type": "tab", "tab": "gc"}]}])["runs"][0]
    for col in ("Created but not sent", "Sent", "Viewed", "Won/Approved", "Deposit received"):
        assert "<h2>%s<span>" % col in run["first"]["list"], col
    assert "Job v-fresh" in run["first"]["list"] and "Job v-gc" not in run["first"]["list"]
    assert "Job v-gc" in run["last"]["list"] and "Job v-fresh" not in run["last"]["list"]
    assert run["first"]["count"] == "6 estimates"
    assert "Reads the 300 most recently updated projects" in run["first"]["ceiling"]


def test_search_filters_cards_by_name_and_estimator(payload):
    run = _run(payload, [{"name": "s", "actions": [{"type": "search", "value": "unpriced"}]}])["runs"][0]
    assert "Job v-unpriced" in run["last"]["list"] and "Job v-fresh" not in run["last"]["list"]
    assert run["last"]["count"] == "1 of 6" and run["last"]["clearHidden"] is False
    run = _run(payload, [{"name": "s", "actions": [{"type": "search", "value": "kyle"}]}])["runs"][0]
    assert run["last"]["count"] == "6 estimates"      # all six are Kyle's, so nothing is hidden


def test_a_failed_read_is_its_own_state(monkeypatch):
    out = _run({"ok": False, "error": "Couldn't load the v2 estimates.", "proposals": []},
               [{"name": "f", "actions": []}])["runs"][0]
    assert "Could not load the v2 estimates." in out["first"]["list"]
    assert out["first"]["toolbarHidden"] is True


def test_an_empty_board_explains_where_bids_come_from(monkeypatch):
    out = _run(_v2(monkeypatch, drafts=[_draft("r", polish_beta=False)], portal=[]),
               [{"name": "e", "actions": []}])["runs"][0]
    assert "No v2 estimates yet." in out["first"]["list"]


def test_the_page_has_no_month_or_sort_controls_and_says_beta():
    html = (FRONTEND / "v2-board.html").read_text(encoding="utf-8")
    assert 'id="month"' not in html and 'id="sort"' not in html and 'id="dir"' not in html
    assert '<span class="tag">Beta</span>' in html
    assert "<h1>Estimating Tool v2</h1>" in html
    assert "<title>Estimating Tool v2 · Treadwell Proposal Generator</title>" in html
    assert '<button type="button" class="btn" id="new-v2">New estimate</button>' in html
    # house rule: no em dash in copy. Read with a parser, so a comment or the stylesheet is not copy.
    assert "—" not in markup(html, attrs_as_text=True).text


# ── D. the panel stays facts ─────────────────────────────────────────────────
FORBIDDEN = re.compile(r"send|follow|deposit|invoice|chat|message|reply|portal|approve (it|this)|hand it off|"
                       r"mark as|mark won|lost reason|data-won|data-lost|data-handoff", re.I)


def test_clicking_a_card_opens_a_read_only_panel_with_one_link(payload):
    run = _run(payload, [{"name": "o", "actions": [{"type": "open", "id": "v-deposit"}]},
                         {"name": "x", "actions": [{"type": "open", "id": "v-deposit"},
                                                   {"type": "escape"}]}])["runs"]
    opened, escaped = run[0], run[1]
    assert opened["last"]["panelOpen"] is True
    panel = opened["last"]["panel"]
    for fact in ("Job v-deposit", "Estimator", "Kyle", "Stage", "Deposit received", "v2 total", "$12,500",
                 "Approved total", "$13,000", "Last updated"):
        assert fact in panel, fact
    assert re.findall(r'href="([^"]*)"', panel) == ["/polish-intake.html?d=v-deposit"]
    assert "Open in Estimating Tool v2" in panel
    assert opened["urls"][-1].endswith("?open=v-deposit")
    assert escaped["last"]["panelOpen"] is False and escaped["urls"][-1] == "/v2-board.html"


def test_the_panel_has_no_customer_facing_or_status_controls(payload):
    panels = _run(payload, [])["core"]["panels"]
    assert panels
    for pid, html in panels.items():
        assert re.findall(r"<button[^>]*>", html) == [
            '<button type="button" class="v2p-close" data-v2-close aria-label="Close">'], pid
        assert not re.search(r"<(input|textarea|select|form)", html, re.I), pid
        # The words a person reads as INSTRUCTIONS: labels, the notice, the link, the close button.
        # The project's own name, its stage ("Deposit received") and chips are facts about the bid.
        text = markup(html, skip=lambda tag, attrs: tag in ("dd", "h2")
                      or (tag == "div" and "chips" in (attrs.get("class") or "").split())).text
        # "Nothing on this panel reaches a customer." is the one sentence allowed to say so
        text = text.replace("Nothing on this panel reaches a customer.", "")
        assert not FORBIDDEN.search(text.replace("Open in Estimating Tool v2", "")), (pid, text)


# ── D2. the card buttons are the Direct Projects ones ────────────────────────
def _buttons(card):
    return re.findall(r"<button[^>]*>([^<]*)</button>", card)


def test_each_card_carries_the_direct_projects_outcome_pair(payload):
    """portal.js cardActions, rule for rule: a live card offers Mark as won/approved and Mark as lost;
    a won or approved one offers Hand it off in place of the win; a lost or handed-off card is
    finished and offers nothing."""
    cards = _run(payload, [])["core"]["cards"]
    for pid in ("v-fresh", "v-gc", "v-test-real", "v-unpriced", "v-viewed"):
        assert _buttons(cards[pid]) == ["Mark as won/approved", "Mark as lost"], pid
    for pid in ("v-won", "v-deposit"):
        assert _buttons(cards[pid]) == ["Hand it off", "Mark as lost"], pid
    for pid in ("v-lost", "v-handed"):
        assert "<button" not in cards[pid], pid
    # the attributes the page's click listener finds them by, carrying the bid's own id
    assert 'data-won="v-fresh"' in cards["v-fresh"] and 'data-lost="v-fresh"' in cards["v-fresh"]
    assert 'data-handoff="v-won"' in cards["v-won"]


def test_plus_new_sits_only_in_created_but_not_sent_on_the_live_tabs(payload):
    run = _run(payload, [{"name": "d", "actions": []},
                         {"name": "g", "actions": [{"type": "tab", "tab": "gc"}]},
                         {"name": "l", "actions": [{"type": "tab", "tab": "lost"}]},
                         {"name": "h", "actions": [{"type": "tab", "tab": "handed_off"}]}])["runs"]
    for live in run[:2]:
        board = live["last"]["list"]
        assert board.count("data-new-v2") == 1, live["name"]
        head = board.split("data-new-v2")[0].rsplit("<h2>", 1)[1]
        assert head.startswith("Created but not sent"), head
    for dead in run[2:]:
        assert "data-new-v2" not in dead["last"]["list"], dead["name"]


def test_mark_as_won_posts_the_won_mark_to_the_draft_and_moves_the_card(payload):
    run = _run(payload, [{"name": "w", "actions": [{"type": "won", "id": "v-fresh"}]}])["runs"][0]
    writes = [f for f in run["fetches"] if f["method"] != "GET"]
    assert writes == [{"url": "/api/draft/v-fresh/status", "method": "POST", "body": {"status": "won"}}]
    # no prompt, as on Direct Projects, and the board re-reads after the write
    assert run["confirms"] == [] and run["dialogs"] == []
    assert run["fetches"][-1] == {"url": "/api/v2/pipeline", "method": "GET"}
    assert run["opened"] == [], "a card button sent the browser somewhere"


def test_hand_it_off_asks_when_the_contacts_are_not_in_and_posts_only_on_yes(payload):
    yes = _run(payload, [{"name": "y", "actions": [{"type": "handoff", "id": "v-won"}]}])["runs"][0]
    assert [c["title"] for c in yes["confirms"]] == ["Hand it off anyway?"]
    assert [f for f in yes["fetches"] if f["method"] != "GET"] == [
        {"url": "/api/draft/v-won/status", "method": "POST", "body": {"status": "handed_off"}}]
    no = _run(payload, [{"name": "n", "confirm": False,
                         "actions": [{"type": "handoff", "id": "v-won"}]}])["runs"][0]
    assert len(no["confirms"]) == 1
    assert [f for f in no["fetches"] if f["method"] != "GET"] == [], "Not yet still handed it off"


def test_hand_it_off_does_not_ask_once_the_contacts_are_in(payload):
    rows = [dict(p, contacts_status="received") if p["proposal_id"] == "v-deposit" else p
            for p in payload["proposals"]]
    run = _run(dict(payload, proposals=rows),
               [{"name": "r", "actions": [{"type": "handoff", "id": "v-deposit"}]}])["runs"][0]
    assert run["confirms"] == []
    assert [f["body"] for f in run["fetches"] if f["method"] != "GET"] == [{"status": "handed_off"}]


def test_mark_as_lost_on_an_unsent_bid_closes_the_draft_with_the_reason_and_the_note(payload):
    run = _run(payload, [{"name": "l", "actions": [
        {"type": "lost", "id": "v-fresh", "reason": "price", "note": "Wilson was 12% under."}]}])["runs"][0]
    assert [f for f in run["fetches"] if f["method"] != "GET"] == [
        {"url": "/api/draft/v-fresh/status", "method": "POST",
         "body": {"status": "closed_lost", "reason": "price", "note": "Wilson was 12% under."}}]
    seen = run["seen"][0]
    assert seen["go"] == "Close it out" and seen["goDisabled"] is False
    assert "It was never sent, so nothing changes for the customer." in seen["sub"]
    assert run["dialogs"][0]["removed"] is True
    # every close-out reason the real dialog offers
    assert run["dialogs"][0]["html"].count("<option ") == _close_choice_count()


def test_mark_as_lost_on_a_sent_bid_goes_to_the_portal_route_that_stops_the_chasing(payload):
    run = _run(payload, [{"name": "l", "actions": [
        {"type": "lost", "id": "v-viewed", "reason": "price", "note": "Went with Wilson."}]}])["runs"][0]
    assert [f for f in run["fetches"] if f["method"] != "GET"] == [
        {"url": "/api/portal/proposal/v-viewed/status", "method": "POST",
         "body": {"status": "closed_lost", "reason": "price", "note": "Went with Wilson."}}]
    assert "all follow-ups stop" in run["seen"][0]["sub"]


def test_a_hold_reason_pauses_instead_of_closing_on_both_routes(payload):
    hold = next(c["key"] for c in _close_choices() if c["outcome"] == "hold")
    run = _run(payload, [{"name": "h", "actions": [
        {"type": "lost", "id": "v-fresh", "reason": hold, "note": "GC went quiet."},
        {"type": "lost", "id": "v-viewed", "reason": hold, "note": "Owner paused the job."}]}])["runs"][0]
    writes = [f for f in run["fetches"] if f["method"] != "GET"]
    assert writes == [
        {"url": "/api/draft/v-fresh/status", "method": "POST",
         "body": {"status": "on_hold", "reason": hold, "note": "GC went quiet."}},
        {"url": "/api/portal/proposal/v-viewed/status", "method": "POST",
         "body": {"status": "delayed", "months": main.HOLD_PAUSE_MONTHS, "reason": hold,
                  "note": "Owner paused the job."}}]
    assert run["seen"][0]["go"] == "Put it on hold"


def test_the_close_out_needs_a_note_and_cancel_writes_nothing(payload):
    run = _run(payload, [{"name": "c", "actions": [
        {"type": "lost", "id": "v-fresh", "reason": "price", "note": "   "},
        {"type": "lost-cancel", "id": "v-fresh"}]}])["runs"][0]
    assert run["seen"][0]["goDisabled"] is True
    assert [f for f in run["fetches"] if f["method"] != "GET"] == []
    assert run["dialogs"][-1]["removed"] is True


def test_the_hold_length_is_the_one_the_real_board_and_the_server_use():
    board = (FRONTEND / "js" / "v2-board.js").read_text(encoding="utf-8")
    real = (FRONTEND / "js" / "portal.js").read_text(encoding="utf-8")
    ours = int(re.search(r"var HOLD_MONTHS = (\d+);", board).group(1))
    theirs = int(re.search(r"const HOLD_MONTHS = (\d+);", real).group(1))
    assert ours == theirs == main.HOLD_PAUSE_MONTHS


@pytest.mark.parametrize("action,tab,audience", [("new", "direct", None), ("new-top", "direct", None),
                                                 ("new", "gc", "GC")])
def test_plus_new_opens_the_intake_on_a_fresh_bid(payload, action, tab, audience):
    """The three keys every "start a project" door clears (projects.js, portal.js), so the intake mints
    a new bid instead of resuming the last one; from the GC tab the new bid starts as a GC one."""
    acts = ([{"type": "tab", "tab": tab}] if tab != "direct" else []) + [{"type": action}]
    run = _run(payload, [{"name": "n", "local": {"treadwell.proposal_tool.state": "{\"job_name\":\"Old\"}",
                                                 "treadwell.proposal_tool.draft_id": "old-id"},
                          "actions": acts}])["runs"][0]
    assert run["opened"] == ["/polish-intake.html"]
    assert "treadwell.proposal_tool.draft_id" not in run["local"]
    assert ["treadwell.proposal_tool.hydrated_once", None] in run["writes"]
    if audience:
        assert json.loads(run["local"]["treadwell.proposal_tool.state"]) == {"audience": audience}
    else:
        assert "treadwell.proposal_tool.state" not in run["local"]
    assert [f for f in run["fetches"] if f["method"] != "GET"] == []


def _close_choices():
    out = run_node_eval("JSON.stringify(require(process.argv[1] + '/js/crm-core.js').CLOSE_CHOICES)")
    return json.loads(out)


def _close_choice_count():
    return len(_close_choices())


def run_node_eval(expr):
    import subprocess
    proc = subprocess.run(["node", "-e", "process.stdout.write(" + expr + ")", str(FRONTEND)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_the_page_makes_one_get_to_its_own_feed_and_nothing_else(payload):
    """The page's code is EXECUTED through a full walk (tabs, search, estimator, open, close, escape)
    and every request it made is read back: a write on load, or behind a click, shows up here."""
    walk = ACTIONS + [{"type": "open", "id": "v-deposit"}, {"type": "escape"},
                      {"type": "open", "id": "v-viewed"}, {"type": "close"}]
    runs = _run(payload, [{"name": "walk", "actions": walk}, {"name": "idle", "actions": []}])["runs"]
    for run in runs:
        assert run["fetches"] == [{"url": "/api/v2/pipeline", "method": "GET"}], run["fetches"]
        assert run["opened"] == [], "the page sent the browser somewhere on its own"
