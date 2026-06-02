"""Sheet/pricing endpoints: correct shape, compact cells, and conditional-GET
caching (ETag -> 304). gzip itself is verified separately via curl; here we
assert the caching contract and payload shape the frontend relies on."""
import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


# ── /api/sheet/{name} shape + compactness ─────────────────────────────
def test_sheet_endpoint_returns_cells():
    r = client.get("/api/sheet/Epoxy")
    assert r.status_code == 200
    body = r.json()
    assert body["sheet"] == "Epoxy"
    assert isinstance(body["cells"], list) and len(body["cells"]) > 100


def test_cells_are_compact_no_default_fields():
    body = client.get("/api/sheet/Epoxy").json()
    # every cell always carries addr/row/col; default fields must be omitted
    for c in body["cells"]:
        assert "addr" in c and "row" in c and "col" in c
        assert c.get("bold") is not False        # False is omitted, never sent
        assert c.get("italic") is not False
        assert "fontColor" not in c or c["fontColor"]  # never null
    # at least one real value cell exists
    assert any("value" in c for c in body["cells"])


def test_system_dropdown_cell_present():
    body = client.get("/api/sheet/Epoxy").json()
    a22 = next((c for c in body["cells"] if c["addr"] == "A22"), None)
    assert a22 is not None  # the System-1 dropdown anchor


def test_unknown_sheet_404():
    assert client.get("/api/sheet/NoSuchTab").status_code == 404


# ── conditional GET / caching contract ────────────────────────────────
def test_sheet_etag_then_304():
    r1 = client.get("/api/sheet/Epoxy")
    etag = r1.headers.get("etag")
    assert etag, "sheet response must carry an ETag"
    r2 = client.get("/api/sheet/Epoxy", headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert not r2.content  # empty body on 304


def test_pricing_systems_etag_then_304():
    r1 = client.get("/api/pricing/systems")
    assert r1.status_code == 200
    assert "MACRO Flake Single Broadcast" in r1.json()["systems"]
    etag = r1.headers.get("etag")
    assert etag
    r2 = client.get("/api/pricing/systems", headers={"If-None-Match": etag})
    assert r2.status_code == 304


# ── /api/price end-to-end (the canonical bid) ─────────────────────────
def test_price_endpoint_full_bid():
    payload = {
        "systems": [
            {"name": "MACRO Flake Single Broadcast", "sf": 12000},
            {"name": "Dur-A-Gard", "sf": 4000},
        ],
        "extras": [{"label": "Static Dissipative Topcoat", "qty": 3, "unit_price": 275}],
        "bulk_discount": True, "taxable": True,
        "remodel": True, "remodel_rate": 0.07975, "full_bid": True,
    }
    body = client.post("/api/price", json=payload).json()
    assert abs(body["material_total"] - 28811) <= 2
    assert abs(body["full_bid"]["total_base_bid"] - 72369) <= 1
    assert body["extras_total"] == 825
