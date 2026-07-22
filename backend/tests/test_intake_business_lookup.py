"""Static UI contracts for the free business-location intake lookup."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_business_lookup_preserves_project_name_and_fills_location_fields():
    html = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "js" / "index.js").read_text(encoding="utf-8")

    assert 'id="business-input"' in html
    assert 'id="business-results"' in html
    assert 'name="address" id="address-input"' in html
    assert "https://photon.komoot.io/api/" in js
    assert "function fillLocation" in js
    assert "Keep the name Kyle entered" in js
    for field in ("addrInput.value", "cityInput.value", "stateInput.value", "zipInput.value"):
        assert field in js


def test_proposal_base_picker_has_no_noncombo_auto_default():
    js = (ROOT / "frontend" / "js" / "proposal-review.js").read_text(encoding="utf-8")

    assert "Auto (work-type default)" not in js
    assert "wt === \"combo\" ? `<label class=\"pr-baserow\"" in js
    assert "pov.single_bid = {}" in js
