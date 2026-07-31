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
    p1 = _rows(bb.get_analytics())["p1"]
    assert p1["quote"] == 21200.0
    assert p1["won_amount"] == 24000.0
    assert p1["submitted_amount"] == 21200.0
    assert p1["pending_amount"] == -2800.0        # negative is real, not an error
    assert p1["lost_amount"] == 0.0


def test_trades_handle_single_multiple_and_untagged(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    rows = _rows(bb.get_analytics())
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
    rows = _rows(bb.get_analytics())
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
    rows = _rows(bb.get_analytics())
    assert rows["p1"]["awarded_by_id"] == "c1"
    assert rows["p3"]["awarded_by_id"] == ""                # awarded, no awarding company


def test_archived_rows_are_kept_but_deleted_are_dropped(monkeypatch):
    """Analytics is the history. The pipeline board drops archived bids to show
    live work; doing that here would erase closed years from every total."""
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    rows = _rows(bb.get_analytics())
    assert "parch" in rows and rows["parch"]["archived"] is True
    assert "pdel" not in rows


def test_null_dates_survive_as_null(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    rows = _rows(bb.get_analytics())
    assert rows["p2"]["awarded_at"] is None                 # never awarded
    assert rows["p1"]["lost_at"] == "2025-06-01T16:01:15.149Z"


def test_dimensions_are_derived_from_the_rows(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    r = bb.get_analytics()
    assert r["trades"] == ["Epoxy", "Gyp", "Polish"]        # untagged contributes nothing
    assert [e["name"] for e in r["estimators"]] == ["Greg Hoss", "Kyle Loseke"]
    names = {c["id"]: c["name"] for c in r["companies"]}
    assert names["c1"] == "JE Dunn"
    assert names["c9"] == "Unknown company"                 # id with no map entry
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
    r = bb.get_analytics()
    assert r["shown"] == 2 and r["total"] == 5 and r["truncated"] is True


def test_second_read_is_served_from_cache(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    calls = {"n": 0}

    def counted(client, path, params=None):
        calls["n"] += 1
        return _fake_get(client, path, params)

    monkeypatch.setattr(bb, "_get", counted)
    _clear()
    bb.get_analytics()
    after_first = calls["n"]
    assert after_first > 0
    bb.get_analytics()
    assert calls["n"] == after_first          # no second fetch


def test_expired_cache_serves_the_last_snapshot_immediately(monkeypatch):
    """A full history is 40-60 requests. Nobody should wait for it when numbers
    from five minutes ago are sitting right there."""
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    bb.get_analytics()
    bb._analytics_cache.clear()               # simulate the TTL lapsing

    started = {"n": 0}

    class FakeThread:
        def __init__(self, *a, **k):
            started["n"] += 1

        def start(self):
            pass

    monkeypatch.setattr(bb.threading, "Thread", FakeThread)
    r = bb.get_analytics()
    assert r["stale"] is True and len(r["projects"]) == 4
    assert started["n"] == 1                  # refreshed behind the reader
    # The lock the (faked) thread never released must not wedge the next reader.
    try:
        bb._ANALYTICS_REFRESH_LOCK.release()
    except RuntimeError:
        pass


def test_a_basisboard_outage_degrades_instead_of_raising(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")

    def boom(client, path, params=None):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(bb, "_get", boom)
    _clear()
    r = bb.get_analytics()
    assert r["ok"] is False and r["configured"] is True and "error" in r
