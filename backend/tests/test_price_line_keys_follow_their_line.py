"""The words a PRICE line was given, and the lines typed around it, follow THEIR line.

The Proposal step stores a price line's edited words (price_overrides.lines / .lines2) and the lines
the estimator typed above and below it (.before / .after) under the line's key: "option:<tab id>"
(with that option's own tax rows under "option:<tab id>:sales_tax" / ":remodel" / ":total"), or
"manual:<i>" by position. The Estimate step reuses both keys: a deleted copy's id goes to the next
copy (nextCopyId), and removing a manual price line moves every later line up one. Nothing moved the
entries with them, so "Test again 123", typed under one option, would print under the next copy
made, and a removed manual line's words landed on the line after it.

EXECUTED: js/price-line-keys-harness.js runs deleteTab and the manual row's remove button, lifted
verbatim out of estimate-review.js; the result is then rendered through the real renderer.
"""
import io
import json
import pathlib
import shutil
import subprocess

import docx
import pytest
from starlette.requests import Request

import main
import proposal_writer as pw

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
HARNESS = pathlib.Path(__file__).resolve().parent / "js" / "price-line-keys-harness.js"
_MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


@pytest.fixture(scope="module")
def ran():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    p = subprocess.run(["node", str(HARNESS), str(FRONTEND)], capture_output=True, text=True,
                       encoding="utf-8", timeout=60)
    assert p.returncode == 0, "the harness itself failed:\n" + p.stderr
    return json.loads(p.stdout.strip().splitlines()[-1])


def test_removing_a_manual_line_takes_its_entries_and_moves_the_later_ones_up(ran):
    m = ran["manual"]
    assert m["labels"] == ["Mockup", "Extra coat"]
    pov = m["saved"]                                  # what the removal SAVED, not just state
    assert pov["lines"] == {"manual:0": "$100 – Mockup, as agreed",
                            "manual:1": "$300 – Extra coat, frozen"}, pov["lines"]
    assert "manual:1" not in pov["lines2"] and "manual:2" not in pov["lines2"], pov["lines2"]
    assert pov["before"].get("manual:1") == ["above the extra coat"], pov["before"]
    assert "manual:2" not in pov["before"]
    assert pov["after"].get("manual:0") == ["under the mockup"]
    assert "manual:1" not in pov["after"], "the removed line's typed line stayed behind"
    # Nothing that is not a manual line moved.
    assert pov["after"]["option:Copy1"] == ["Test again 123"] and pov["after"]["base"] == ["under the base"]
    # ...and the BULLETS on those lines (the REBID price box's line_props / before_props /
    # after_props) went with their lines: the removed line's are gone, the later line's moved up.
    assert pov["line_props"] == {"manual:1": {"bullet": True, "level": 1},
                                 "option:Copy1": {"bullet": False, "indent": 288},
                                 "option:Copy10": {"bullet": True, "level": 1}}, pov["line_props"]
    assert pov["before_props"] == {"manual:1": [{"bullet": False, "indent": 576}]}, pov["before_props"]
    assert "manual:1" not in pov["after_props"], "the removed line's typed-line bullet stayed behind"


def test_deleting_a_copy_takes_its_option_entries_and_only_its_own(ran):
    t = ran["tab"]
    assert t["copies"] == ["Copy10"]
    pov = t["saved"]
    for bucket in ("lines", "lines2", "before", "after", "line_props", "before_props", "after_props"):
        left = [k for k in pov.get(bucket, {}) if k == "option:Copy1" or k.startswith("option:Copy1:")]
        assert not left, (bucket, left)
    assert pov["line_props"]["option:Copy10"] == {"bullet": True, "level": 1}
    assert pov["after_props"]["option:Copy10"] == [{"bullet": False, "indent": 1440}]
    # "Copy10" shares the prefix and is a different option.
    assert pov["lines2"]["option:Copy10"] == "⟦amount⟧ – kept"
    assert pov["after"]["option:Copy10"] == ["under copy 10"]
    assert pov["after"]["base"] == ["under the base"] and pov["lines2"]["manual:1"]


def test_the_document_prints_each_typed_line_beside_its_own_manual_line(ran):
    """The draft the removal saved, rendered: the words typed above "Extra coat" print directly
    above it (it is manual line 1 now), and the removed line's words print nowhere."""
    pov = ran["manual"]["saved"]
    req = Request({"type": "http", "method": "POST", "path": "/t", "headers": [], "query_string": b""})
    values = {"project_name": "Keys", "job_name": "Keys", "city_state": "Olathe, KS", "texture": "Smooth",
              "system_name": "Epoxy", "scope_notes": "s", "schedule_notes": "s", "exclusions": "e",
              "estimator_name": "Kyle", "bid_date_formatted": "9/26/26", "total_formatted": "$5,000",
              "material_tax_formatted": "$80", "tax_amount_formatted": "$0", "base_bid_formatted": "$5,000",
              "tax_layout": "ONE_LINE", "price_taxable": True, "price_remodel_on": False,
              "epoxy_sf": "100", "sqft": "100"}
    blob = main._render_documents(
        {"work_type": "epoxy", "audience": "Direct", "values": values, "remodel": [],
         "price_lines": [{"label": "Mockup", "amount": 100}, {"label": "Extra coat", "amount": 300}],
         "price_overrides": pov}, req, want_estimate=False)["docx"]["content"]
    d = docx.Document(io.BytesIO(blob))
    texts = [pw._own_text(p) for p in d.element.xpath("//w:p")
             if not any(True for _ in p.iterancestors(f"{_MC}Fallback"))
             and p.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}txbxContent") is None]
    i = texts.index("$300 – Extra coat, frozen")
    assert texts[i - 1] == "above the extra coat", texts[i - 3:i + 2]
    j = texts.index("$100 – Mockup, as agreed")
    assert texts[j + 1] == "under the mockup", texts[j:j + 3]
    assert "under night work" not in texts and not any("Night work" in t for t in texts)
