"""The analytics dataset: row shaping, the cents conversion, dimension lists,
and the serve-stale-while-refreshing cache. No network — `_get` is monkeypatched
exactly as test_basisboard.py does it.

The fixture mirrors real Basisboard data, including the parts that bite:
untagged and multi-tagged trades, a negative pendingAmount, an awarded project
with no awardedById, and a project whose `lostAt` is set even though it was
later awarded."""
import basisboard_client as bb

TRADE_FIELD = "trade-field-uuid"

_PROJECTS = {
    # Awarded, single trade, one estimator, one company.
    "p1": {"id": "p1", "name": "St Paul Catholic Church", "city": "Olathe", "region": "Kansas",
           "quote": 2120000, "wonAmount": 2400000, "submittedAmount": 2120000,
           "pendingAmount": -280000, "lostAmount": 0,
           "stageId": "awarded", "estimatorIds": ["u1"], "bidInviteIds": ["b1"],
           "awardedById": "c1", "customFields": {TRADE_FIELD: ["Epoxy"]},
           "awardedAt": "2026-05-07T13:11:00.000Z", "submittedAt": "2026-03-31T14:06:41.441Z",
           "lostAt": "2025-06-01T16:01:15.149Z",      # set, then later awarded
           "createdAt": "2024-06-28T12:35:00.491Z"},
    # Submitted only, TWO trades, two estimators, two companies.
    "p2": {"id": "p2", "name": "Char Bar - Olathe", "city": "Olathe", "region": "Kansas",
           "quote": 500000, "wonAmount": 0, "submittedAmount": 500000,
           "pendingAmount": 500000, "lostAmount": 0,
           "stageId": "submitted", "estimatorIds": ["u1", "u2"], "bidInviteIds": ["b2", "b3"],
           "customFields": {TRADE_FIELD: ["Epoxy", "Polish"]},
           "submittedAt": "2026-02-10T00:00:00.000Z", "createdAt": "2026-01-02T00:00:00.000Z"},
    # UNTAGGED trade (the field comes back as ""), no estimator, awarded with no
    # awardedById, and no bid invites at all.
    "p3": {"id": "p3", "name": "Hoss and Brown", "quote": 100000, "wonAmount": 100000,
           "submittedAmount": 100000, "stageId": "awarded", "estimatorIds": [],
           "bidInviteIds": [], "customFields": {TRADE_FIELD: ""},
           "awardedAt": "2026-06-01T00:00:00.000Z", "submittedAt": "2026-01-15T00:00:00.000Z",
           "createdAt": "2025-12-01T00:00:00.000Z"},
    # ARCHIVED — history, so analytics keeps it (the pipeline board drops it).
    "parch": {"id": "parch", "name": "Archived Job", "stageId": "lost", "archivedAt": "2026-02-02",
              "quote": 900000, "submittedAmount": 900000, "wonAmount": 0,
              "customFields": {TRADE_FIELD: ["Gyp"]}, "bidInviteIds": ["b4"],
              "submittedAt": "2025-03-03T00:00:00.000Z", "createdAt": "2025-01-01T00:00:00.000Z"},
    # DELETED — dropped everywhere.
    "pdel": {"id": "pdel", "name": "Deleted Job", "stageId": "lost", "deletedAt": "2026-02-02",
             "customFields": {TRADE_FIELD: ["Epoxy"]}},
}
ALL_IDS = list(_PROJECTS)

_INVITES = {
    "b1": {"id": "b1", "companyId": "c1", "bidDeadlineAt": "2024-08-07T19:00:00.000Z"},
    "b2": {"id": "b2", "companyId": "c2", "bidDeadlineAt": "2026-02-01T00:00:00.000Z"},
    # Later deadline + a DIFFERENT company: both must surface.
    "b3": {"id": "b3", "companyId": "c3", "bidDeadlineAt": "2026-02-05T00:00:00.000Z"},
    "b4": {"id": "b4", "companyId": "c9"},                   # no deadline at all
}
_COMPANIES = {
    "c1": {"id": "c1", "name": "JE Dunn"},
    "c2": {"id": "c2", "name": "McCown Gordon"},
    "c3": {"id": "c3", "name": "Turner"},
    # c9 deliberately absent from the map — an unresolvable company id.
}
_STAGES = [
    {"id": "awarded", "name": "Awarded", "color": "#1f7a34", "order": 3},
    {"id": "submitted", "name": "Submitted", "color": "#264b8b", "order": 2},
    {"id": "lost", "name": "Lost", "color": "#8a8a8a", "order": 4},
    {"id": "quiet", "name": "Undecided", "color": "#cccccc", "order": 1},   # zero rows
]


def _fake_get(client, path, params=None):
    if path == "/stages":
        return {"stages": _STAGES}
    if path == "/users":
        off = int((params or {}).get("offset", 0))
        users = [{"id": "u1", "firstName": "Kyle", "lastName": "Loseke"},
                 {"id": "u2", "firstName": "Greg", "lastName": "Hoss"}]
        return {"users": users[off:off + 13]}
    if path == "/custom-field-settings":
        return {"customFieldSettings": [
            {"id": "other-uuid", "name": "Google Lead?"},
            {"id": TRADE_FIELD, "name": "Trades"},
        ]}
    if path == "/projects/ids":
        off = int((params or {}).get("offset", 0))
        lim = int((params or {}).get("limit", 50))
        return {"projectIds": ALL_IDS[off:off + lim], "paging": {"total": len(ALL_IDS)}}
    if path == "/projects":
        ids = (params or {}).get("filter[projectIds][]", [])
        return {"projects": [_PROJECTS[i] for i in ids if i in _PROJECTS],
                "bidInvitesMap": _INVITES, "companiesMap": _COMPANIES}
    raise AssertionError("unexpected path " + path)


def _clear():
    bb._meta_cache.clear()
    bb._analytics_cache.clear()
    bb._analytics_last_good.clear()
    bb._analytics_state.update({"building": False, "error": ""})
    try:                                        # a failed test can leave it held
        bb._ANALYTICS_REFRESH_LOCK.release()
    except RuntimeError:
        pass
    # AND THE SNAPSHOT ON DISK. The build path writes one (basisboard_client._SNAPSHOT_FILE), and
    # a later "cold read" test then finds a warm cache and reports no `building` at all. In CI every
    # run gets a fresh container so it never showed up there; on a dev box the file persists, so the
    # suite passed once and failed on every run after. Clearing memory without clearing disk is
    # only half of _clear.
    try:
        bb._SNAPSHOT_FILE.unlink()
    except OSError:
        pass
    bb._PACER._interval = bb._PACER._floor
    bb._PACER._next_at = 0.0


def build(monkeypatch):
    """The dataset, built synchronously.

    `get_analytics()` deliberately never blocks — reading the whole history is
    dozens of paced requests — so it hands the work to a thread. Tests want the
    answer, not the concurrency, so they run the build inline."""
    return bb._build_analytics()


def _rows(payload):
    return {r["id"]: r for r in payload["projects"]}


def test_unconfigured_is_inert(monkeypatch):
    monkeypatch.delenv("BASISBOARD_API_KEY", raising=False)
    _clear()
    calls = {"n": 0}
    monkeypatch.setattr(bb, "_get", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {})
    r = bb.get_analytics()
    assert r["ok"] is False and r["configured"] is False
    assert calls["n"] == 0


def test_money_is_converted_from_cents(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    p1 = _rows(build(monkeypatch))["p1"]
    assert p1["quote"] == 21200.0
    assert p1["won_amount"] == 24000.0
    assert p1["submitted_amount"] == 21200.0
    assert p1["pending_amount"] == -2800.0        # negative is real, not an error
    assert p1["lost_amount"] == 0.0


def test_trades_handle_single_multiple_and_untagged(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    rows = _rows(build(monkeypatch))
    assert rows["p1"]["trades"] == ["Epoxy"]
    assert rows["p2"]["trades"] == ["Epoxy", "Polish"]
    assert rows["p3"]["trades"] == []             # the field is "" on untagged jobs


def test_parse_trades_shapes():
    assert bb._parse_trades(["Epoxy", " Polish "]) == ["Epoxy", "Polish"]
    assert bb._parse_trades(["Epoxy", "", None]) == ["Epoxy"]
    assert bb._parse_trades("Gyp") == ["Gyp"]
    assert bb._parse_trades("") == []
    assert bb._parse_trades(None) == []
    assert bb._parse_trades(0) == []


def test_companies_and_deadline_come_from_the_bid_invites(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    rows = _rows(build(monkeypatch))
    assert rows["p1"]["company_ids"] == ["c1"]
    assert rows["p2"]["company_ids"] == ["c2", "c3"]
    assert rows["p3"]["company_ids"] == []                  # no invites
    # A project carries no deadline of its own — the latest invite's is the one.
    assert rows["p2"]["bid_deadline_at"] == "2026-02-05T00:00:00.000Z"
    assert rows["p3"]["bid_deadline_at"] is None
    assert rows["parch"]["bid_deadline_at"] is None         # invite with no deadline


def test_awarded_by_is_passed_through_and_may_be_missing(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    rows = _rows(build(monkeypatch))
    assert rows["p1"]["awarded_by_id"] == "c1"
    assert rows["p3"]["awarded_by_id"] == ""                # awarded, no awarding company


def test_archived_rows_are_kept_but_deleted_are_dropped(monkeypatch):
    """Analytics is the history. The pipeline board drops archived bids to show
    live work; doing that here would erase closed years from every total."""
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    rows = _rows(build(monkeypatch))
    assert "parch" in rows and rows["parch"]["archived"] is True
    assert "pdel" not in rows


def test_null_dates_survive_as_null(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    rows = _rows(build(monkeypatch))
    assert rows["p2"]["awarded_at"] is None                 # never awarded
    assert rows["p1"]["lost_at"] == "2025-06-01T16:01:15.149Z"


def test_dimensions_are_derived_from_the_rows(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    r = build(monkeypatch)
    assert r["trades"] == ["Epoxy", "Gyp", "Polish"]        # untagged contributes nothing
    assert [e["name"] for e in r["estimators"]] == ["Greg Hoss", "Kyle Loseke"]
    names = {c["id"]: c["name"] for c in r["companies"]}
    assert names["c1"] == "JE Dunn"
    # An id with no record behind it still owns real history, so it gets a
    # bucket — tagged with the id so two unknowns don't collapse into one line.
    assert names["c9"] == "Unknown company (c9)"
    # Every stage, including one no row is in: the filter list shouldn't flicker
    # as the date window moves.
    assert [s["name"] for s in r["stages"]] == ["Undecided", "Submitted", "Awarded", "Lost"]


def test_trade_field_is_resolved_by_name(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    assert bb._fetch_trade_field_id(None) == TRADE_FIELD


def test_trade_field_falls_back_when_settings_are_unavailable(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")

    def boom(client, path, params=None):
        if path == "/custom-field-settings":
            raise RuntimeError("500")
        return _fake_get(client, path, params)

    monkeypatch.setattr(bb, "_get", boom)
    _clear()
    assert bb._fetch_trade_field_id(None) == bb._TRADE_FIELD_FALLBACK


def test_cap_marks_the_payload_truncated(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setenv("ANALYTICS_MAX_PROJECTS", "2")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    r = build(monkeypatch)
    assert r["shown"] == 2 and r["total"] == 5 and r["truncated"] is True


def run_pending(monkeypatch):
    """Capture the background build so a test can run it itself.

    Patches the module's own `_spawn`, NOT threading.Thread: the latter also
    replaces the workers inside ThreadPoolExecutor, and the build then waits
    forever on futures no thread will complete."""
    jobs = []
    monkeypatch.setattr(bb, "_spawn", lambda fn, name: jobs.append(fn))
    return jobs


def test_a_cold_read_never_blocks_and_says_it_is_building(monkeypatch):
    """Reading the whole history is dozens of paced requests; a page load can't
    wait on it. The first caller starts the work and gets a state it can
    render."""
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    jobs = run_pending(monkeypatch)

    r = bb.get_analytics()
    assert r["ok"] is True and r["building"] is True and r["projects"] == []
    assert len(jobs) == 1

    # A second reader arriving mid-build must not start a second one.
    r2 = bb.get_analytics()
    assert r2["building"] is True and len(jobs) == 1

    jobs[0]()                                    # the build finishes
    done = bb.get_analytics()
    assert done["ok"] is True and not done.get("building")
    assert len(done["projects"]) == 4


def test_the_history_is_read_in_big_pages(monkeypatch):
    """Page size is what keeps this fast. At 50 rows a page the full history is
    ~136 requests — a big enough burst that Basisboard starts answering 429, and
    the backed-off build takes two minutes instead of ten seconds."""
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    seen = {"ids": [], "detail": []}

    def watched(client, path, params=None):
        if path == "/projects/ids":
            seen["ids"].append(int((params or {}).get("limit", 0)))
        if path == "/projects":
            seen["detail"].append(len((params or {}).get("filter[projectIds][]", [])))
        return _fake_get(client, path, params)

    monkeypatch.setattr(bb, "_get", watched)
    _clear()
    build(monkeypatch)
    assert seen["ids"] and set(seen["ids"]) == {bb._ANALYTICS_ID_PAGE}
    assert bb._ANALYTICS_ID_PAGE >= 200 and bb._ANALYTICS_DETAIL_PAGE >= 100
    assert max(seen["detail"]) <= bb._ANALYTICS_DETAIL_PAGE
    # The pipeline board keeps its own smaller page — this must not have moved it.
    assert bb._PAGE == 50


def test_a_warm_read_costs_no_requests(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    calls = {"n": 0}

    def counted(client, path, params=None):
        calls["n"] += 1
        return _fake_get(client, path, params)

    monkeypatch.setattr(bb, "_get", counted)
    _clear()
    jobs = run_pending(monkeypatch)
    bb.get_analytics()
    jobs[0]()
    after_build = calls["n"]
    assert after_build > 0
    bb.get_analytics()
    bb.get_analytics()
    assert calls["n"] == after_build                    # served from cache


def test_an_expired_cache_serves_the_last_snapshot_immediately(monkeypatch):
    """Nobody should wait two minutes for numbers when the ones from five
    minutes ago are sitting right there."""
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    jobs = run_pending(monkeypatch)
    bb.get_analytics()
    jobs[0]()

    bb._analytics_cache.clear()                         # the TTL lapses
    r = bb.get_analytics()
    assert r["stale"] is True and len(r["projects"]) == 4
    assert len(jobs) == 2                               # refreshing behind the reader


def test_a_basisboard_outage_degrades_instead_of_raising(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")

    def boom(client, path, params=None):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(bb, "_get", boom)
    _clear()
    jobs = run_pending(monkeypatch)
    assert bb.get_analytics()["building"] is True
    jobs[0]()                                    # the build fails

    # It tries again — but says the last one failed, so an outage doesn't read
    # as a build that simply never finishes.
    r = bb.get_analytics()
    assert r["ok"] is True and r["building"] is True
    assert r["last_error"]
    assert len(jobs) == 2


def test_the_build_lock_is_released_even_when_the_build_fails(monkeypatch):
    """A held lock would wedge the page on 'building' forever."""
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")

    def boom(client, path, params=None):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(bb, "_get", boom)
    _clear()
    jobs = run_pending(monkeypatch)
    bb.get_analytics()
    jobs[0]()
    assert bb._analytics_state["building"] is False
    assert bb._ANALYTICS_REFRESH_LOCK.acquire(blocking=False) is True
    bb._ANALYTICS_REFRESH_LOCK.release()
