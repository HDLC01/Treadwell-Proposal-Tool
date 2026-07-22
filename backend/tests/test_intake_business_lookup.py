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


def test_broken_out_tax_preview_uses_current_total_and_total_label():
    """Persisted draft tokens must not mask the newly selected tax treatment."""
    js = (ROOT / "frontend" / "js" / "proposal-review.js").read_text(encoding="utf-8")
    start = js.index("const tokenValues = {")
    end = js.index("    };", start)
    values = js[start:end]

    # Draft values are only defaults. The current calculation must overwrite
    # them, so a saved '(tax exempt)' phrase cannot survive broken-out tax.
    assert values.index("...mergedValues,") < values.index("total_label:")
    assert "total_label:        `${fmtUSD(lumpSumNumber)} – Total`" in values
    assert "if (m.broken) return \"\";" in values


def test_broken_out_tax_can_change_before_template_rows_mount():
    """An early tax selector change must not block the Proposal → Done handoff."""
    js = (ROOT / "frontend" / "js" / "proposal-review.js").read_text(encoding="utf-8")

    for name in ("salesTaxDisplay", "remodelTaxDisplay", "totalDisplay"):
        assert f"const {name} = document.getElementById" in js
        assert f"if ({name}) {name}.textContent" in js


def test_proposal_continue_button_has_a_direct_handoff_listener():
    """The ribbon button is outside the hidden form, so it cannot rely on submit."""
    html = (ROOT / "frontend" / "proposal-review.html").read_text(encoding="utf-8")
    js = (ROOT / "frontend" / "js" / "proposal-review.js").read_text(encoding="utf-8")

    assert '<button type="button" id="generate-btn">Continue to Done' in html
    assert "async function continueToDone(e)" in js
    assert "const earlyGenerateBtn = document.getElementById(\"generate-btn\");" in js
    assert "earlyGenerateBtn.onclick = continueToDone;" in js
