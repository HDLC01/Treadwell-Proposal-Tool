"""The v2 Estimates board (BETA): its own route, its own code, separate from the real boards.

Hanz, 2026-10-13: "make the V2 have a pipeline like the ones we have for active projects", "make sure
they are separate tho", then "the V2 pipeline is still in beta ... so do not merge it to the
existing". So the board is built as NEW code that reads the shared, DOM-free crm-core.js, and the
existing boards (portal.js, portal.html, /gc-projects.html, notifications.js and the
/api/portal/pipeline route) are not touched.

WHAT HAS TO HOLD
  A. /api/v2/pipeline returns v2 (polish_beta) drafts and only those, from creation, test copies
     included, and TWCrm.stage files each one in the right column.
  B. THE REAL BOARDS ARE UNCHANGED: pinned hashes of the files and of the route's source, and the
     default /api/portal/pipeline answer for a mixed fixture is byte-for-byte what it was (no v2
     field, and a never-generated v2 draft is still not on it).
  C. SEPARATE STORAGE: every key the board writes starts tw_v2_; seeding the real boards' keys
     changes nothing it reads; localStorage is never touched (the harness throws if it is).
  D. READ ONLY: the panel carries no send, follow-up, deposit, chat or status control.
  E. THE PAGE: Direct and GC tabs by audience, test copies on the board with a chip, no price is a
     dash and never $0, search kept, month and sort gone.

Everything JavaScript here is EXECUTED (tests/js/v2-board-harness.js), not read as source text.
"""
import hashlib
import inspect
import json
import pathlib
import re
import tempfile

import pytest
from fastapi.testclient import TestClient

import main
import v2_pipeline
from _node import last_json_line, run_node

client = TestClient(main.app)
ROOT = pathlib.Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "v2-board-harness.js"


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
def _sha(data: bytes) -> str:
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


# PINNED ON PURPOSE (Hanz, 2026-10-13: the v2 board is beta and must not be merged into the existing
# boards). A legitimate edit to one of these files fails here: update the hash IN THE SAME COMMIT, and
# say why in the message. What this stops is the v2 board changing them by accident or on the side.
PINS = {
    "js/portal.js": "4d12a99fb89f40651cb95f2ce9a20c5433fc33e0685ecfee10de92b574476951",
    "portal.html": "e47981196e32f9d347e28bce24aa72461feac7db7d0f44fd79edfcca716c616a",
    "js/notifications.js": "8591c436cc4ed3823e9afa1fe76c76e37e5a9f22cc6dba1ad52e98bc99e39970",
}
ROUTE_PIN = "882a3d8f2e5e11d9e525e34b21659cfca2b84f9b279b6c1904e58cb4e2ff8160"


@pytest.mark.parametrize("name", sorted(PINS))
def test_the_real_boards_files_are_unchanged(name):
    assert _sha((FRONTEND / name).read_bytes()) == PINS[name], (
        "%s changed. The v2 board is built beside the real boards and must not edit them. If this "
        "edit is deliberate and has nothing to do with v2, update the pin in this file." % name)


def test_the_existing_pipeline_route_is_unchanged():
    got = _sha(inspect.getsource(main.api_portal_pipeline).encode("utf-8"))
    assert got == ROUTE_PIN, "api_portal_pipeline changed; the v2 board has its own route"


@pytest.mark.parametrize("name", ["js/portal.js", "portal.html", "js/notifications.js"])
def test_the_real_boards_know_nothing_about_v2(name):
    text = (FRONTEND / name).read_text(encoding="utf-8")
    for token in ("tw_v2_", "/api/v2/", "v2-board", "TWV2Board"):
        assert token not in text, "%s mentions %s" % (name, token)


def test_the_v2_code_never_loads_or_calls_portal_js():
    html = (FRONTEND / "polish-estimates.html").read_text(encoding="utf-8")
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
    html = (FRONTEND / "polish-estimates.html").read_text(encoding="utf-8")
    assert 'id="month"' not in html and 'id="sort"' not in html and 'id="dir"' not in html
    assert '<span class="tag">Beta</span>' in html
    assert 'href="/polish-intake.html">Open Estimating Tool v2</a>' in html
    assert "—" not in re.sub(r"<!--.*?-->|<style.*?</style>", "", html, flags=re.S)


# ── D. read only ─────────────────────────────────────────────────────────────
FORBIDDEN = re.compile(r"send|follow|deposit|invoice|chat|message|reply|portal|approve (it|this)|hand it off|"
                       r"mark as|mark won|lost reason|data-won|data-lost|data-handoff", re.I)


def test_clicking_a_card_opens_a_read_only_panel_with_one_link(payload):
    run = _run(payload, [{"name": "o", "actions": [{"type": "open", "id": "v-deposit"}]},
                         {"name": "x", "actions": [{"type": "open", "id": "v-deposit"},
                                                   {"type": "escape"}]}])["runs"]
    opened, escaped = run[0], run[1]
    assert opened["last"]["panelOpen"] is True
    panel = opened["last"]["panel"]
    for fact in ("Job v-deposit", "Estimator", "Kyle", "Stage", "Deposit received", "v2 total", "$13,000",
                 "Last updated"):
        assert fact in panel, fact
    assert re.findall(r'href="([^"]*)"', panel) == ["/polish-intake.html?d=v-deposit"]
    assert "Open in Estimating Tool v2" in panel
    assert opened["urls"][-1].endswith("?open=v-deposit")
    assert escaped["last"]["panelOpen"] is False and escaped["urls"][-1] == "/polish-estimates.html"


def test_the_panel_has_no_customer_facing_or_status_controls(payload):
    panels = _run(payload, [])["core"]["panels"]
    assert panels
    for pid, html in panels.items():
        assert re.findall(r"<button[^>]*>", html) == [
            '<button type="button" class="v2p-close" data-v2-close aria-label="Close">'], pid
        assert not re.search(r"<(input|textarea|select|form)", html, re.I), pid
        # The words a person reads as INSTRUCTIONS: labels, the notice, the link, the close button.
        # The project's own name, its stage ("Deposit received") and chips are facts about the bid.
        static = re.sub(r'<(dd|h2)[^>]*>.*?</(?:dd|h2)>|<div class="chips">.*?</div>', " ", html, flags=re.S)
        text = re.sub(r"<[^>]+>", " ", static)
        # "Read only. Nothing on this panel reaches a customer." is the one sentence allowed to say so
        text = text.replace("Nothing on this panel reaches a customer.", "")
        assert not FORBIDDEN.search(text.replace("Open in Estimating Tool v2", "")), (pid, text)
    # and the cards carry no action buttons either
    cards = _run(payload, [])["core"]["cards"]
    assert not any("<button" in c for c in cards.values())
