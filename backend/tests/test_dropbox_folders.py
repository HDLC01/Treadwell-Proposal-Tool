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


# ── what the FIRST live run against real Dropbox exposed ─────────────────────
def _stub_live(monkeypatch, cats, owners):
    from dropbox.files import FolderMetadata

    class _Res:
        def __init__(self, names):
            self.entries = [FolderMetadata(name=n) for n in names]
            self.has_more = False

    class _Client:
        def files_list_folder(self, path):
            return _Res(cats if path.endswith("Estimating") else owners)

    monkeypatch.setattr(dropbox_client, "_build_client", lambda: _Client())
    dropbox_client._FOLDER_CACHE.update(at=0.0, data=None)


def test_existing_destinations_keep_their_legacy_keys(monkeypatch):
    """/api/to-dropbox resolves paths BY KEY. The live listing first emitted
    '$commercial_sales_estimates' instead of 'commercial', which would have made
    every filing request fail with "Unknown destination folder"."""
    _stub_live(monkeypatch, ["$Gyp Estimates", "$Commercial Sales Estimates",
                             "$Plans Specs Estimates"], ["*Kyle"])
    try:
        keys = {d["key"] for d in dropbox_client.list_estimating_folders()["destinations"]}
    finally:
        dropbox_client._FOLDER_CACHE.update(at=0.0, data=None)
    assert keys == {"gyp", "commercial", "plans_specs"}      # unchanged, not slugified


def test_the_bid_template_is_never_offered_as_a_destination(monkeypatch):
    """$$ Bid Template is what each project folder is COPIED FROM — filing a job
    into it would corrupt the template for everyone."""
    _stub_live(monkeypatch, ["$$ Bid Template", "$Gyp Estimates"], [])
    try:
        labels = [d["label"] for d in dropbox_client.list_estimating_folders()["destinations"]]
    finally:
        dropbox_client._FOLDER_CACHE.update(at=0.0, data=None)
    assert labels == ["Gyp Estimates"]


def test_liz_and_troy_are_hidden_even_though_the_folders_exist(monkeypatch):
    """Will asked for them off the picker; we don't delete anyone's Dropbox
    folders, so the live listing still returns them and we filter here."""
    _stub_live(monkeypatch, ["$Commercial Sales Estimates"],
               ["*Liz", "*Kyle", "*Troy", "*Hanz", "*RJ"])
    try:
        owners = [o["label"] for o in dropbox_client.list_estimating_folders()["owners"]]
    finally:
        dropbox_client._FOLDER_CACHE.update(at=0.0, data=None)
    assert owners == ["Hanz", "Kyle", "RJ"]


def test_a_new_folder_is_filable_immediately(monkeypatch):
    _stub_live(monkeypatch, ["$Gyp Estimates", "$Service Work Estimates"], [])
    try:
        assert dropbox_client.destination_path("service_work_estimates") == \
            "/2023 Treadwell Team Folder/Estimating/$Service Work Estimates"
    finally:
        dropbox_client._FOLDER_CACHE.update(at=0.0, data=None)


def test_destination_path_falls_back_when_dropbox_is_down(monkeypatch):
    monkeypatch.setattr(dropbox_client, "list_estimating_folders",
                        lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert dropbox_client.destination_path("gyp") == dropbox_client.ESTIMATING_DESTINATIONS["gyp"]
    assert dropbox_client.destination_path("nope") is None
    assert dropbox_client.destination_path("") is None
