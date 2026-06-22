"""Read-only Basisboard client: pipeline assembly, field shaping, and the
inert-when-unconfigured contract. No network — `_get` is monkeypatched, mirroring
how test_security_misc/test_dropbox_naming avoid live calls."""
import basisboard_client as bb

ALL_IDS = ["p1", "p2", "p3", "parch", "pdel"]
_PROJECTS = {
    "p1": {"id": "p1", "name": "Bravo Job", "location": "Olathe, KS", "quote": 50000,
           "stageId": "s1", "estimatorIds": ["u1"], "awardedAt": None, "archivedAt": None, "deletedAt": None},
    "p2": {"id": "p2", "name": "Alpha Job", "location": "N/A", "quote": None,
           "stageId": "s2", "estimatorIds": [], "awardedAt": "2026-01-01", "archivedAt": None, "deletedAt": None},
    "p3": {"id": "p3", "name": "Zeta Job", "location": "KC, MO", "quote": 12000,
           "stageId": "sX", "estimatorIds": ["u1"], "awardedAt": None, "archivedAt": None, "deletedAt": None},
    "parch": {"id": "parch", "name": "Archived Job", "stageId": "s1", "archivedAt": "2026-02-02"},
    "pdel": {"id": "pdel", "name": "Deleted Job", "stageId": "s1", "deletedAt": "2026-02-02"},
}


def _fake_get(client, path, params=None):    # client arg ignored in tests
    if path == "/stages":
        return {"stages": [
            {"id": "s1", "name": "Estimating", "color": "#c8102e", "order": 1, "code": "estimating"},
            {"id": "s2", "name": "Won", "color": "#0a6b2c", "order": 2, "code": "won"},
        ]}
    if path == "/users":
        return {"users": [{"id": "u1", "firstName": "Kyle", "lastName": "Loseke",
                           "email": "kyle@wetreadwell.com"}]}
    if path == "/projects/ids":
        off = int((params or {}).get("offset", 0))
        lim = int((params or {}).get("limit", 50))
        return {"projectIds": ALL_IDS[off:off + lim], "paging": {"total": len(ALL_IDS)}}
    if path == "/projects":
        ids = (params or {}).get("filter[projectIds][]", [])
        return {"projects": [_PROJECTS[i] for i in ids if i in _PROJECTS]}
    raise AssertionError("unexpected path " + path)


def _clear():
    bb._meta_cache.clear()
    bb._pipeline_cache.clear()


def test_not_configured_returns_inert(monkeypatch):
    monkeypatch.delenv("BASISBOARD_API_KEY", raising=False)
    _clear()
    assert bb.is_configured() is False
    r = bb.get_pipeline()
    assert r["ok"] is False and r["configured"] is False


def test_unconfigured_makes_no_http_call(monkeypatch):
    monkeypatch.delenv("BASISBOARD_API_KEY", raising=False)
    _clear()
    calls = {"n": 0}
    monkeypatch.setattr(bb, "_get", lambda *a, **k: calls.__setitem__("n", calls["n"] + 1) or {})
    bb.get_pipeline()
    assert calls["n"] == 0          # never touches the API when the key is absent


def test_pipeline_shapes_filters_and_sorts(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    _clear()
    r = bb.get_pipeline()
    assert r["ok"] is True and r["configured"] is True
    assert r["total"] == 5 and r["shown"] == 3      # 5 ids, archived + deleted dropped

    names = [p["name"] for p in r["projects"]]
    assert "Deleted Job" not in names and "Archived Job" not in names
    # sorted by (stage_order, name): s1=1 -> Bravo, s2=2 -> Alpha, unknown=9999 -> Zeta
    assert names == ["Bravo Job", "Alpha Job", "Zeta Job"]

    p1 = next(p for p in r["projects"] if p["id"] == "p1")
    assert p1["stage_name"] == "Estimating" and p1["stage_color"] == "#c8102e"
    assert p1["estimators"] == ["Kyle Loseke"] and p1["value"] == 50000

    p2 = next(p for p in r["projects"] if p["id"] == "p2")
    assert p2["location"] == "" and p2["awarded"] is True and p2["value"] is None  # "N/A" blanked

    p3 = next(p for p in r["projects"] if p["id"] == "p3")
    assert p3["stage_name"] == "Unstaged"               # unknown stage id

    assert [s["name"] for s in r["stages"]] == ["Estimating", "Won"]   # ordered columns


def test_id_paging_respects_cap(monkeypatch):
    monkeypatch.setenv("BASISBOARD_API_KEY", "test-key")
    monkeypatch.setattr(bb, "_get", _fake_get)
    monkeypatch.setenv("BASISBOARD_MAX_PROJECTS", "2")
    _clear()
    ids, total = bb._fetch_project_ids(None, bb._max_projects())   # client unused (mocked _get)
    assert ids == ["p1", "p2"] and total == 5          # capped to 2, total still reported
