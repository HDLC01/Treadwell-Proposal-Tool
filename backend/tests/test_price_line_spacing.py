"""A space the estimator types into the Base Bid line must reach the document.

Kyle, 2026-08-20: "I added a space on this but it didnt retain in the proposal documents.
When I go back it doesnt save it in the current position."

His draft is on production, named "Spacing test", and the stored data says the save half
works: `price_overrides.lines.base` and the pinned
`proposal_payload.price_overrides.lines.base` are byte-identical and both carry his two
spaces, so nothing is stripping it on the way in and the snapshot is not stale. His
project is epoxy/Direct, so the `_rows_ok` gate passes too.

What his draft also says is `tax_inclusion: INCLUDED` — and the existing whole-line
whitespace test runs in BROKEN_OUT. This file covers the mode he is actually in, with the
exact string from his draft.
"""
from __future__ import annotations

import pytest

from tests.test_price_overrides import _VALS, _rendered, _xml, client

# Verbatim from the production draft, two spaces before the parenthesis.
KYLE_BASE = "$7,774.00 – Epoxy flooring as described above  (material sales tax INCLUDED)"


def _generate(mode: str, base: str):
    vals = dict(_VALS)
    vals["tax_inclusion"] = mode
    body = {"work_type": "epoxy", "audience": "Direct", "values": vals,
            "price_overrides": {"lines": {"base": base}}}
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200, r.text
    return client.get(r.json()["docx_download_url"]).content


@pytest.mark.parametrize("mode", ["INCLUDED", "BROKEN_OUT"])
def test_a_typed_double_space_reaches_the_document(mode):
    """The whole complaint, in both tax layouts. INCLUDED is the one Kyle is in and the
    one nothing covered before."""
    xml = _xml(_generate(mode, KYLE_BASE))
    collapsed = KYLE_BASE.replace("above  (", "above (")
    assert KYLE_BASE in xml, (
        "the estimator's second space was lost in %s mode; the document has %r"
        % (mode, "collapsed" if collapsed in xml else "neither form"))


@pytest.mark.parametrize("mode", ["INCLUDED", "BROKEN_OUT"])
def test_leading_and_trailing_spaces_reach_the_document(mode):
    """Word drops whitespace at the edges of a <w:t> without xml:space="preserve", so the
    edges are the fragile case, not the middle."""
    xml = _xml(_generate(mode, "  edge spaces  kept  "))
    assert "  edge spaces  kept  " in xml
    assert 'xml:space="preserve"' in xml


def test_the_included_layout_really_is_a_different_path():
    """A guard on the premise: if INCLUDED and BROKEN_OUT produced identical documents,
    the parametrisation above would be testing one thing twice."""
    inc = _rendered(_generate("INCLUDED", KYLE_BASE))
    bro = _rendered(_generate("BROKEN_OUT", KYLE_BASE))
    assert inc != bro, "the two tax layouts render the same — re-read this file"


# ── Enter for spacing: the row must not keep a bullet it has no text for ──────
import re as _re  # noqa: E402


def _work_paragraphs(xml):
    return _re.findall(r"<w:p\b.*?</w:p>", xml, _re.S)


def _para_after(xml, marker):
    """The paragraph following the one containing `marker` — how we reach the Notes row
    without hard-coding an index that template edits would rot."""
    paras = _work_paragraphs(xml)
    for i, p in enumerate(paras):
        if marker in "".join(_re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p)):
            return paras[i + 1] if i + 1 < len(paras) else None
    return None


def _gen_para_override(overrides):
    body = {"work_type": "epoxy", "audience": "Direct", "values": dict(_VALS),
            "paragraph_overrides": overrides}
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200, r.text
    return _xml(client.get(r.json()["docx_download_url"]).content)


def test_the_notes_row_is_bulleted_before_anyone_edits_it():
    """The premise. If this row stopped being a list item, the test below would pass for
    the wrong reason."""
    p = _para_after(_gen_para_override([]), "Exclusions")
    assert p is not None, "could not locate the Notes row"
    assert "<w:numPr>" in p, "the Notes row is no longer bulleted — re-read this file"
    assert "Notes:" in "".join(_re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))


def test_pressing_enter_for_spacing_leaves_no_orphan_bullet():
    """Kyle's actual production override, verbatim: [{"id": 118, "text": "\n"}] on the
    'Notes:  {{work_notes}}' row, after he pressed Enter to add spacing and reported "it
    did not generate in the proposal".

    It DID generate — the break was written — but the paragraph kept its numbering, so
    what printed was a lone red square on an empty row. Blank vertical space is what he
    asked for; a stray bullet is not it. Same rule the notes block already applies to a
    blank {{#notes}} item."""
    p = _para_after(_gen_para_override([{"id": 118, "text": "\n"}]), "Exclusions")
    assert p is not None, "could not locate the Notes row"
    assert p.count("<w:br/>") == 1, "the typed break did not reach the document"
    assert "<w:numPr>" not in p, (
        "a blanked row kept its bullet — the customer's proposal has a lone bullet dot "
        "on an empty line")


def test_a_row_blanked_with_formatting_also_loses_its_bullet():
    """The override channel carries two shapes. A run list that is all-empty is just as
    blank as an empty string, and must not be treated differently."""
    p = _para_after(_gen_para_override([{"id": 118, "runs": [{"text": "", "bold": True}]}]),
                    "Exclusions")
    assert p is not None
    assert "<w:numPr>" not in p, "a run-list blank kept its bullet"


def test_a_row_with_real_text_KEEPS_its_bullet():
    """The guard that stops this becoming a bullet-stripper. Kyle's WORK bullets are
    template design and a 2026-07-16 decision keeps them; only a row with nothing in it
    loses one."""
    p = _para_after(_gen_para_override([{"id": 118, "text": "Notes:  see attached"}]),
                    "Exclusions")
    assert p is not None
    assert "<w:numPr>" in p, "an edited row lost the bullet it is supposed to keep"
    assert "see attached" in "".join(_re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))
