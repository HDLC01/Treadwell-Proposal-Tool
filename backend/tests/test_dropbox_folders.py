"""Live Dropbox folder listing for step 5.

The destination and owner pickers used to be hardcoded in two places, so adding
or deleting a folder in Dropbox changed nothing. They now come from a live
listing — with the constants kept purely as a fallback, because the filing step
must never dead-end just because Dropbox had a bad minute.
"""
import dropbox_client
import main
from fastapi.testclient import TestClient

client = TestClient(main.app)


def test_slug_matches_the_value_the_ui_posts_back():
    assert dropbox_client._slug("*Kyle") == "kyle"
    assert dropbox_client._slug("*Mary Jane") == "mary_jane"


def test_liz_and_troy_are_gone_from_the_fallback():
    assert set(dropbox_client.COMMERCIAL_OWNER_SUBFOLDERS) == {"kyle", "hanz", "rj"}


def test_endpoint_returns_the_live_listing(monkeypatch):
    monkeypatch.setattr(dropbox_client, "list_estimating_folders", lambda: {
        "destinations": [{"key": "gyp_estimates", "label": "Gyp Estimates", "path": "/x/$Gyp Estimates"},
                         {"key": "commercial_sales_estimates", "label": "Commercial Sales Estimates",
                          "path": "/x/$Commercial Sales Estimates"}],
        "commercial_key": "commercial_sales_estimates",
        "owners": [{"key": "kyle", "label": "Kyle", "folder": "*Kyle"},
                   {"key": "dana", "label": "Dana", "folder": "*Dana"}],   # added in Dropbox today
    })
    j = client.get("/api/dropbox/folders").json()
    assert j["ok"] is True and j["live"] is True
    assert [o["key"] for o in j["owners"]] == ["kyle", "dana"]     # picks up the new folder


def test_endpoint_falls_back_when_dropbox_is_down(monkeypatch):
    def boom():
        raise RuntimeError("dropbox unreachable")
    monkeypatch.setattr(dropbox_client, "list_estimating_folders", boom)
    j = client.get("/api/dropbox/folders").json()
    assert j["ok"] is True and j["live"] is False
    assert {d["key"] for d in j["destinations"]} == set(dropbox_client.ESTIMATING_DESTINATIONS)
    assert {o["key"] for o in j["owners"]} == {"kyle", "hanz", "rj"}


def test_owner_folder_resolves_from_the_live_listing(monkeypatch):
    """A person added in Dropbox must file correctly without a deploy."""
    monkeypatch.setattr(dropbox_client, "list_estimating_folders", lambda: {
        "destinations": [], "commercial_key": None,
        "owners": [{"key": "dana", "label": "Dana", "folder": "*Dana"}]})
    assert dropbox_client.commercial_owner_subfolder("dana") == "*Dana"


def test_owner_folder_falls_back_to_the_constants(monkeypatch):
    def boom():
        raise RuntimeError("down")
    monkeypatch.setattr(dropbox_client, "list_estimating_folders", boom)
    assert dropbox_client.commercial_owner_subfolder("kyle") == "*Kyle"
    assert dropbox_client.commercial_owner_subfolder("") == ""
    assert dropbox_client.commercial_owner_subfolder("nobody") == ""


def test_listing_calls_the_client_the_way_the_rest_of_the_module_does(monkeypatch):
    """Regression: this called `dbx, FolderMetadata = _build_client()`, but
    _build_client returns the client ALONE — it blew up with "cannot unpack
    non-iterable Dropbox object" the first time it hit real Dropbox. The existing
    tests only ever stubbed list_estimating_folders, so nothing exercised the call."""
    from dropbox.files import FolderMetadata      # real type: the filter is an isinstance check

    class _Res:
        def __init__(self, names):
            self.entries = [FolderMetadata(name=n) for n in names]
            self.has_more = False

    calls = []

    class _Client:
        def files_list_folder(self, path):
            calls.append(path)
            return _Res(["$Gyp Estimates", "$Commercial Sales Estimates"] if path.endswith("Estimating")
                        else ["*Kyle", "*Hanz"])

    monkeypatch.setattr(dropbox_client, "_build_client", lambda: _Client())
    dropbox_client._FOLDER_CACHE.update(at=0.0, data=None)      # bypass the TTL cache
    try:
        d = dropbox_client.list_estimating_folders()
    finally:
        dropbox_client._FOLDER_CACHE.update(at=0.0, data=None)
    assert [x["label"] for x in d["destinations"]] == ["Commercial Sales Estimates", "Gyp Estimates"]
    assert [o["label"] for o in d["owners"]] == ["Hanz", "Kyle"]
    assert calls[0].endswith("/Estimating")
