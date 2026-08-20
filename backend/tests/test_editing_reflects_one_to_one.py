"""What the estimator types is what the customer gets, character for character.

Kyle, 2026-08-20, after adding a space to a PRICE Options line and finding it gone from
the generated document: "everything in the Proposals when editing should refelect 1 to 1
in the customer side."

The Base Bid line kept his space and the Options line did not, because they travel by two
different channels. A whole-line edit went through a branch whose comment says "NEVER
trim"; the Options rows are per-field ISLANDS (amount / desc / tax_phrase), and BOTH the
browser handler and the server sanitiser trimmed each island. The seam between two
adjacent islands is exactly where a person adds a space, so it was exactly what got eaten
-- twice, independently.

These tests pin the whole path for every price field, not just the one that happened to
work.
"""
from __future__ import annotations

import pytest

import main
from tests.test_price_overrides import _VALS, _rendered, _xml, client


# ── the server sanitiser, field by field ─────────────────────────────────────
def test_the_sanitiser_keeps_spaces_on_every_price_field():
    """One rule for all of them. `lines` already preserved spaces and said so; the island
    fields silently did the opposite."""
    out = main._sanitize_price_overrides({
        "options":   {"7": {"label": "  padded label  ", "amount": " $1  "}},
        "manual":    [{"label": "  a  b  ", "amount": " $2 "}],
        "single_bid": {"desc": "as described above  ", "tax_phrase": "  (tax INCLUDED)"},
        "rows":      {"total": {"label": "  Total  ", "amount": " $3 "}},
        "alternate": {"name": "  Alt  "},
        "lines":     {"base": "  whole line  "},
    })
    assert out["options"]["7"]["label"] == "  padded label  "
    assert out["options"]["7"]["amount"] == " $1  "
    assert out["manual"][0]["label"] == "  a  b  "
    assert out["single_bid"]["desc"] == "as described above  "
    assert out["single_bid"]["tax_phrase"] == "  (tax INCLUDED)"
    assert out["rows"]["total"]["label"] == "  Total  "
    assert out["alternate"]["name"] == "  Alt  "
    assert out["lines"]["base"] == "  whole line  "


@pytest.mark.parametrize("blank", ["", "   ", "\n", " \n "])
def test_a_whitespace_only_edit_still_reverts(blank):
    """The one thing the strip was genuinely for. An empty edit means "put the computed
    value back", and that must survive preserving spaces everywhere else."""
    out = main._sanitize_price_overrides({
        "options": {"7": {"label": blank}},
        "single_bid": {"desc": blank},
        "lines": {"base": blank},
    })
    assert "7" not in out["options"] or "label" not in out["options"]["7"]
    assert "desc" not in out["single_bid"]
    assert "base" not in out["lines"]


# ── and the whole way into the document ──────────────────────────────────────
def _docx(body):
    r = client.post("/api/generate", json=body)
    assert r.status_code == 200, r.text
    return client.get(r.json()["docx_download_url"]).content


def test_kyles_option_line_space_reaches_the_document():
    """His exact shape: a space added at the seam before the tax phrase on an OPTION row,
    which is the case that failed while the Base Bid line worked."""
    # Needs a real option row for the override to attach to, so this mirrors the
    # existing option-line test's setup (rooms + a manual price line).
    from tests.test_price_overrides import _rooms
    body = {"work_type": "epoxy", "audience": "Direct", "values": dict(_VALS),
            "rooms": _rooms(), "price_lines": [{"label": "Add VE", "amount": 2500}],
            "price_overrides": {"lines": {
                "option:Copy1": "$24,086 – Polish in Weekend Phases (3 max) as described "
                                "above  (material sales tax INCLUDED)"}}}
    xml = _xml(_docx(body))
    assert "as described above  (material sales tax INCLUDED)" in xml, (
        "the second space was dropped on an option line")


def test_the_base_bid_line_still_works_too():
    """A guard against fixing one channel and breaking the other."""
    vals = dict(_VALS)
    vals["tax_inclusion"] = "INCLUDED"
    body = {"work_type": "epoxy", "audience": "Direct", "values": vals,
            "price_overrides": {"lines": {"base": "$17,166.00 – Polished Concrete  "
                                                  "(material sales tax INCLUDED)"}}}
    assert "Polished Concrete  (material" in _xml(_docx(body))


def test_no_price_write_path_trims_the_stored_value():
    """The browser half, asserted against the shipped source rather than a copy of it.

    Three sites write a stored override (two island handlers and the whole-line one). All
    three must collapse newlines only. A `.trim()` on any of them silently re-creates
    Kyle's bug on that channel alone, which is exactly how it hid: one channel was right
    and nothing compared them.
    """
    import pathlib
    js = (pathlib.Path(__file__).resolve().parents[2] / "frontend" / "js"
          / "proposal-review.js").read_text(encoding="utf-8")
    writes = [ln.strip() for ln in js.split("\n")
              if "serializeBlock(sp)" in ln or "serializeBlock(lineNode)" in ln]
    assert len(writes) == 3, "the set of price write paths changed: %r" % writes
    for w in writes:
        assert ".trim()" not in w, "a price write path trims again: %s" % w

def test_the_islands_show_the_spaces_they_store():
    """The DISPLAY half, which the write-path test cannot see.

    `nowrap` and `pre` both stop an island wrapping mid-parenthesis, which is why the
    rule exists -- but `nowrap` still COLLAPSES a run of spaces, so Kyle's second space
    was invisible on screen even once it was stored correctly. A fix that only corrects
    storage leaves him typing a space he cannot see, which reads as broken either way.
    """
    import pathlib as _p
    css = (_p.Path(__file__).resolve().parents[2] / "frontend" / "styles.css").read_text(
        encoding="utf-8")
    import re
    m = re.search(r"#base-bid-row \.tw-fill[^{]*\{([^}]*)\}", css)
    assert m, "the price-island white-space rule is gone -- rewrite this test"
    ws = re.search(r"white-space\s*:\s*([\w-]+)", m.group(1))
    assert ws, "the price islands no longer set white-space at all"
    assert ws.group(1) in ("pre", "pre-wrap"), (
        "price islands are %r, which collapses runs of spaces -- a typed double space "
        "would be invisible on screen" % ws.group(1))


# ── indenting, and moving to the next line ───────────────────────────────────
# Kyle, 2026-08-21: "also when I indent or move it to the next line does it apply as
# well?" Measured rather than assumed, and the two halves of the editor answer
# differently, so both are pinned here.

@pytest.mark.parametrize("kind,val", [
    ("leading indent",   "    $1 - indented four spaces"),
    ("interior run",     "$1 - two  spaces  here"),
    ("trailing spaces",  "$1 - trailing   "),
])
def test_a_price_line_keeps_indents_and_runs_of_spaces(kind, val):
    """Indenting is the same mechanism as Kyle's Options space: leading whitespace was
    being trimmed, so an indent could never survive. It does now."""
    body = {"work_type": "epoxy", "audience": "Direct", "values": dict(_VALS),
            "price_overrides": {"lines": {"base": val}}}
    assert val in _xml(_docx(body)), "%s was lost from a price line" % kind


@pytest.mark.parametrize("kind,val,breaks", [
    ("next line",  "first line\nsecond line", 1),
    ("blank line", "first\n\nthird", 2),
])
def test_a_work_row_turns_a_typed_newline_into_a_real_break(kind, val, breaks):
    """Enter in a WORK row gives a real <w:br/>, so "move it to the next line" works
    there. Two Enters give a blank line, which is the spacing case."""
    body = {"work_type": "epoxy", "audience": "Direct", "values": dict(_VALS),
            "paragraph_overrides": [{"id": 115, "text": val}]}
    xml = _xml(_docx(body))
    # the row exists twice in the file (modern shape + legacy fallback), so allow either copy
    assert xml.count("<w:br/>") >= breaks, "%s did not reach the document" % kind


def test_the_writer_would_accept_a_newline_in_a_price_line_too():
    """Documents the boundary honestly. The WRITER has no problem with a break in a price
    line -- posting one straight to the API produces real <w:br/> elements. What flattens
    Enter to a space there is a deliberate choice in the browser handler ("a price line is
    one line"), NOT a limitation of the .docx. Recorded so that if Kyle asks for Enter to
    work in Base Bid and Options, whoever picks it up knows it is a one-line client change
    and not a writer rewrite."""
    body = {"work_type": "epoxy", "audience": "Direct", "values": dict(_VALS),
            "price_overrides": {"lines": {"base": "$1 - first\nsecond"}}}
    assert _xml(_docx(body)).count("<w:br/>") >= 1


def test_two_blank_lines_mean_two_blank_lines():
    """Hanz, 2026-08-21: "if they enter two blank lines then it should also be 2 blank
    lines." The editor used to flatten every newline in a price line to a single space, so
    the count was always zero. Measured: three newlines produce three breaks per copy of
    the line (the row exists twice in the file, as the modern shape and its legacy
    fallback), so the assertion is on the RATIO rather than a raw count."""
    def breaks(val):
        body = {"work_type": "epoxy", "audience": "Direct", "values": dict(_VALS),
                "price_overrides": {"lines": {"base": val}}}
        return _xml(_docx(body)).count("<w:br/>")
    one  = breaks("$1 - a" + chr(10) + "b")
    three = breaks("$1 - a" + chr(10) * 3 + "b")
    assert one > 0, "a typed newline reaches the document at all"
    assert three == one * 3, (
        "three newlines gave %d breaks where one gave %d - runs are being collapsed"
        % (three, one))

