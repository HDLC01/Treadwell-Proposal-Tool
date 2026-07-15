"""Phase B — the base-bid tab's ROLE drives the whole proposal.

proposal-review.js keys the proposal (template, area/noun, narrative, notes, and
the generate payload's work_type) off `effectiveWorkType()` — the resolved base
tab's role — instead of the raw intake `state.work_type`. So when the estimator
sets a polish sheet as the base bid on an epoxy job, the ENTIRE proposal follows
the base ("really pulling the right data").

These are grep guards (CI can't drive the browser): they document the wiring and
catch a silent revert to a hardcoded `state.work_type`. The behavior itself is
verified with Playwright on staging.
"""
import pathlib
import re

_FE = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "js"
_PROP_JS = (_FE / "proposal-review.js").read_text(encoding="utf-8")


def test_effective_work_type_helper_defined():
    # The helper exists and combo stays combo (the base switch there only picks
    # which sub-bid leads — the template doesn't change).
    m = re.search(r"function effectiveWorkType\(\)\s*\{(.*?)\n  \}", _PROP_JS, re.S)
    assert m, "effectiveWorkType() not found"
    body = m.group(1)
    assert 'if (wt === "combo") return "combo"' in body
    assert "state.base_tab_id" in body and ".role" in body


def test_token_values_use_effective_work_type():
    # computeTokenValues drives area_description / noun / sqft off the effective
    # type, not the raw intake work_type.
    m = re.search(r"function computeTokenValues\(mergedValues\)\s*\{(.*?)\n    const sa =",
                  _PROP_JS, re.S)
    assert m, "computeTokenValues head not found"
    assert "const workType = effectiveWorkType();" in m.group(1)


def test_template_load_and_media_use_effective_work_type():
    # The template fetch and the artwork fetch both follow the effective type so a
    # base switch reloads the right .docx + PNGs.
    assert re.search(r"async function initDocumentEditor\(\)\s*\{\s*\n\s*const wt = effectiveWorkType\(\);",
                     _PROP_JS), "initDocumentEditor must resolve wt via effectiveWorkType()"
    assert re.search(r"function artUrl\(name\)\s*\{\s*\n\s*const wt = effectiveWorkType\(\);",
                     _PROP_JS), "artUrl must resolve wt via effectiveWorkType()"
    # And the media cache is keyed by work type so a reload can't serve a stale PNG.
    assert 'const key = wt + ":" + name;' in _PROP_JS


def test_generate_payload_work_type_is_effective():
    # The payload the Done page POSTs to /api/generate carries the EFFECTIVE work
    # type, so the backend picks the base role's template.
    m = re.search(r"proposal_payload:\s*\{(.*?)\n      \}", _PROP_JS, re.S)
    assert m, "proposal_payload block not found"
    assert "work_type: effectiveWorkType()," in m.group(1)


def test_base_switch_triggers_reload():
    # Flipping a base-bid radio re-derives the whole proposal when the role changed.
    assert "reloadForWorkType()" in _PROP_JS
    m = re.search(r"function reloadForWorkType\(\)\s*\{(.*?)\n  \}", _PROP_JS, re.S)
    assert m, "reloadForWorkType() not found"
    body = m.group(1)
    for fn in ("adaptToWorkType()", "seedNarrative(true)",
               "reseedNotesForWorkType()", "initDocumentEditor()"):
        assert fn in body, f"reloadForWorkType must call {fn}"
    # Guarded: no-op when the effective type is unchanged (same-role base switch).
    assert "if (cur === _lastEffWt) return;" in body


def test_sheet_systems_bail_for_non_epoxy_effective_type():
    # The epoxy-only {{#system}} picks must not leak into a polish/gyp payload.
    m = re.search(r"function sheetSystems\(\)\s*\{(.*?)\n    const all =", _PROP_JS, re.S)
    assert m, "sheetSystems() head not found"
    assert 'if (_ewt !== "epoxy" && _ewt !== "combo") return null;' in m.group(1)
